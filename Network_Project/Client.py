import socket
import threading

HOST = "127.0.0.1"
PORT = 5000

client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
client.connect((HOST, PORT))


def receive_messages():
    buffer = b""

    try:
        while True:
            data = client.recv(1024)
            if not data:
                break

            buffer += data
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                print(line.decode())
    except OSError:
        pass


threading.Thread(target=receive_messages, daemon=True).start()

try:
    while True:
        message = input()
        client.sendall(message.encode() + b"\n")
except (EOFError, KeyboardInterrupt):
    pass
finally:
    client.close()