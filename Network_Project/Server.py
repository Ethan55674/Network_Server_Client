import json
import socket
import struct
import threading

HOST = "0.0.0.0"
PORT = 5000
CHUNK_SIZE = 64 * 1024
MAX_HEADER_SIZE = 64 * 1024
MAX_TRANSFER_SIZE = 1024 * 1024 * 1024

clients = set()
clients_lock = threading.Lock()
broadcast_lock = threading.Lock()


def receive_exact(connection, byte_count):
    data = bytearray()

    while len(data) < byte_count:
        chunk = connection.recv(min(CHUNK_SIZE, byte_count - len(data)))
        if not chunk:
            return None
        data.extend(chunk)

    return bytes(data)


def remove_client(client):
    with clients_lock:
        clients.discard(client)
    client.close()


def handle_client(client, address):
    print(f"Connected: {address}")

    with clients_lock:
        clients.add(client)

    try:
        while True:
            header_length_data = receive_exact(client, 4)
            if header_length_data is None:
                break

            header_length = struct.unpack("!I", header_length_data)[0]
            if not 0 < header_length <= MAX_HEADER_SIZE:
                break

            header_data = receive_exact(client, header_length)
            if header_data is None:
                break

            try:
                metadata = json.loads(header_data.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                break

            kind = metadata.get("type")
            size = metadata.get("size")
            if (
                kind not in {"text", "file"}
                or not isinstance(size, int)
                or isinstance(size, bool)
                or not 0 <= size <= MAX_TRANSFER_SIZE
            ):
                break

            metadata["sender"] = address[0]
            forwarded_header = json.dumps(metadata).encode("utf-8")
            frame_header = struct.pack("!I", len(forwarded_header)) + forwarded_header

            with broadcast_lock:
                with clients_lock:
                    recipients = tuple(other for other in clients if other is not client)

                active_recipients = []
                for recipient in recipients:
                    try:
                        recipient.sendall(frame_header)
                        active_recipients.append(recipient)
                    except OSError:
                        remove_client(recipient)

                remaining = size
                while remaining:
                    chunk = client.recv(min(CHUNK_SIZE, remaining))
                    if not chunk:
                        return

                    remaining -= len(chunk)
                    failed_recipients = []
                    for recipient in active_recipients:
                        try:
                            recipient.sendall(chunk)
                        except OSError:
                            failed_recipients.append(recipient)

                    for recipient in failed_recipients:
                        active_recipients.remove(recipient)
                        remove_client(recipient)
    except OSError:
        pass
    finally:
        remove_client(client)
        print(f"Disconnected: {address}")


with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, PORT))
    server.listen()
    print(f"Listening on port {PORT}")

    while True:
        client, address = server.accept()
        threading.Thread(
            target=handle_client,
            args=(client, address),
            daemon=True,
        ).start()