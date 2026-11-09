import json
import socket
import struct
import threading
from pathlib import Path
import shlex

HOST = "127.0.0.1"
PORT = 5000
CHUNK_SIZE = 64 * 1024
MAX_HEADER_SIZE = 64 * 1024
MAX_TRANSFER_SIZE = 1024 * 1024 * 1024
SUPPORTED_FILE_TYPES = {".mp4",}
DOWNLOAD_DIR = Path("downloads")

client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
client.connect((HOST, PORT))


def receive_exact(connection, byte_count):
    data = bytearray()

    while len(data) < byte_count:
        chunk = connection.recv(min(CHUNK_SIZE, byte_count - len(data)))
        if not chunk:
            return None
        data.extend(chunk)

    return bytes(data)


def send_header(metadata):
    header = json.dumps(metadata).encode("utf-8")
    client.sendall(struct.pack("!I", len(header)) + header)


def send_text(message):
    payload = message.encode("utf-8")
    send_header({"type": "text", "size": len(payload)})
    client.sendall(payload)


def send_file(file_path):
    if not file_path.is_file():
        raise ValueError(f"Not a file: {file_path}")
    if file_path.suffix.lower() not in SUPPORTED_FILE_TYPES:
        raise ValueError("Choose an audio file or an MP4 file.")

    file_size = file_path.stat().st_size
    if file_size > MAX_TRANSFER_SIZE:
        raise ValueError("File exceeds the 1 GiB transfer limit.")

    send_header({
        "type": "file",
        "name": file_path.name,
        "size": file_size,
    })

    with file_path.open("rb") as file:
        while chunk := file.read(CHUNK_SIZE):
            client.sendall(chunk)

    print(f"Sent {file_path.name} ({file_size} bytes)")


def unique_download_path(filename):
    DOWNLOAD_DIR.mkdir(exist_ok=True)
    safe_name = Path(filename.replace("\\", "/")).name or "received-file"
    destination = DOWNLOAD_DIR / safe_name
    counter = 1

    while destination.exists():
        destination = DOWNLOAD_DIR / f"{Path(safe_name).stem} ({counter}){Path(safe_name).suffix}"
        counter += 1

    return destination


def receive_messages():
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

            sender = metadata.get("sender", "Unknown")
            if kind == "text":
                payload = receive_exact(client, size)
                if payload is None:
                    break
                print(f"\n{sender}: {payload.decode('utf-8', errors='replace')}")
            else:
                destination = unique_download_path(str(metadata.get("name", "received-file")))
                remaining = size
                try:
                    with destination.open("wb") as file:
                        while remaining:
                            chunk = client.recv(min(CHUNK_SIZE, remaining))
                            if not chunk:
                                raise ConnectionError("Transfer ended unexpectedly.")
                            file.write(chunk)
                            remaining -= len(chunk)
                except (ConnectionError, OSError):
                    destination.unlink(missing_ok=True)
                    break

                print(f"\n{sender} sent a file: {destination}")
    except OSError:
        pass


threading.Thread(target=receive_messages, daemon=True).start()
print('Type a message, or use /file "path/to/file.mp4" to send a file.')

try:
    while True:
        message = input("> ")
        if message.startswith("/file"):
            try:
                command = shlex.split(message)
                if len(command) != 2 or command[0] != "/file":
                    raise ValueError('Usage: /file "path/to/file.mp4"')
                send_file(Path(command[1]))
            except (OSError, ValueError) as error:
                print(error)
        elif message:
            send_text(message)
except (EOFError, KeyboardInterrupt, OSError):
    pass
finally:
    client.close()