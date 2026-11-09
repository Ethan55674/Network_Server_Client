import socket
import threading

HOST = "0.0.0.0"
PORT = 5000

clients = set()
clients_lock = threading.Lock()


def broadcast(message, sender):
    with clients_lock:
        recipients = clients.copy()

    for client in recipients:
        if client is sender:
            continue
        try:
            client.sendall(message)
        except OSError:
            with clients_lock:
                clients.discard(client)
            client.close()


def handle_client(client, address):
    print(f"Connected: {address}")

    with clients_lock:
        clients.add(client)

    buffer = b""

    try:
        while True:
            data = client.recv(1024)
            if not data:
                break

            buffer += data
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                if line:
                    message = f"{address[0]}: ".encode() + line + b"\n"
                    broadcast(message, client)
    except OSError:
        pass
    finally:
        with clients_lock:
            clients.discard(client)
        client.close()
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