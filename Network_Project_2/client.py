# client.py
# run it with   python client.py
#
# Commands
#   connect <server_ip> <port>
#   upload <local_file> [server_name]
#   download <server_name>
#   delete <server_name>
#   dir [folder]
#   subfolder create|delete <path>
#   quit
import hashlib
import os
import socket
import time
from analysis import StatsCollector

CHUNK_SIZE = 64 * 1024
stats = StatsCollector("client_stats.csv")
server_socket = None    # stays None until we connect
logged_in_user = ""


# Sending and receiving
def send_message(text):
    data = text.encode()
    server_socket.sendall(len(data).to_bytes(4, "big") + data)


def receive_exact_bytes(how_many):
    # recv can give us less than we asked for
    # so this loop keeps calling it until we have all the bytes we need
    data = b""
    while len(data) < how_many:
        piece = server_socket.recv(how_many - len(data))
        if not piece:
            raise ConnectionError("server closed the connection")
        data += piece
    return data


def receive_message():
    length = int.from_bytes(receive_exact_bytes(4), "big")
    return receive_exact_bytes(length).decode()


def send_command_and_get_reply(command_text):
    # also times how long the server takes to answer which is the response time
    start = time.time()
    send_message(command_text)
    reply = receive_message()
    return reply, time.time() - start


def print_server_reply(reply):
    # replies start with OK or ERROR so we cut that part off before printing
    if reply.startswith("OK"):
        print(reply[3:])
    else:
        print("Error:", reply[6:])


def print_transfer_speed(num_bytes, seconds):
    megabytes = num_bytes / (1024 * 1024)
    print("%.2f MB in %.2f seconds (%.2f MB/s)" % (megabytes, seconds, megabytes / max(seconds, 0.0001)))


# Connect
def connect_to_server(server_ip, port):
    global server_socket, logged_in_user
    username = input("Username: ")
    password = input("Password: ")

    try:
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.connect((server_ip, port))

        # we send the hash of the password so the real password is never sent
        password_hash = hashlib.sha256(password.encode()).hexdigest()
        send_message(username + " " + password_hash)
        reply = receive_message()
    except OSError as error:
        # OSError happens when the connection fails
        # for example the ip is wrong or the server is not running
        print("Could not connect:", error)
        server_socket = None
        return

    if reply.startswith("OK"):
        logged_in_user = username
        print("Connected as", username)
    else:
        print_server_reply(reply)
        server_socket.close()
        server_socket = None


# File operations
def upload_file(local_path, server_name):
    if not os.path.isfile(local_path):
        print("Local file not found:", local_path)
        return

    reply, response_seconds = send_command_and_get_reply("upload|" + server_name)

    # the server says EXISTS when it already has a file with this name
    if reply == "EXISTS":
        answer = input("That file already exists on the server. Overwrite? (yes/no): ")
        if answer.lower() not in ("y", "yes"):
            send_message("no")
            print("Upload cancelled")
            return
        send_message("yes")
    elif not reply.startswith("OK"):
        print_server_reply(reply)
        return

    file_size = os.path.getsize(local_path)
    print("Uploading...")
    transfer_start = time.time()
    send_message(str(file_size))
    with open(local_path, "rb") as f:
        # read the file one piece at a time and send each piece until the file is finished
        while True:
            piece = f.read(CHUNK_SIZE)
            if not piece:
                break
            server_socket.sendall(piece)

    reply = receive_message()    # the server tells us when it has saved the file
    transfer_seconds = time.time() - transfer_start
    print_server_reply(reply)
    print_transfer_speed(file_size, transfer_seconds)
    stats.record_operation(logged_in_user, "upload", server_name, file_size,
                           transfer_seconds, response_seconds)


def download_file(server_name):
    reply, response_seconds = send_command_and_get_reply("download|" + server_name)
    if not reply.startswith("OK"):
        print_server_reply(reply)    # for example File does not exist
        return

    os.makedirs("downloads", exist_ok=True)
    save_path = os.path.join("downloads", os.path.basename(server_name))
    print("Downloading...")
    transfer_start = time.time()
    file_size = int(receive_message())
    received = 0
    with open(save_path, "wb") as f:
        # keep receiving pieces and writing them until we have the whole file
        while received < file_size:
            amount = min(CHUNK_SIZE, file_size - received)
            f.write(receive_exact_bytes(amount))
            received += amount
    transfer_seconds = time.time() - transfer_start

    print("Saved to", save_path)
    print_transfer_speed(file_size, transfer_seconds)
    stats.record_operation(logged_in_user, "download", server_name, file_size,
                           transfer_seconds, response_seconds)


def run_simple_command(command_text, name, operation_name):
    # delete and dir and subfolder all work the same way
    # send the command and print the answer and record the response time
    reply, response_seconds = send_command_and_get_reply(command_text)
    print_server_reply(reply)
    stats.record_operation(logged_in_user, operation_name, name, 0, 0, response_seconds)


# Command input
def command_loop():
    global server_socket
    print("Commands: connect <ip> <port>, upload <file> [name], download <name>, delete <name>,")
    print("dir [folder], subfolder create|delete <path> , quit")

    # this loop keeps asking the user for a command until they type quit
    while True:
        words = input("> ").split()    # typing  upload a.txt  gives us ["upload", "a.txt"]
        if len(words) == 0:
            continue
        command = words[0].lower()

        if command == "quit":
            break

        if command == "connect":
            if len(words) == 3 and words[2].isdigit():
                connect_to_server(words[1], int(words[2]))
            else:
                print("Use: connect <server_ip> <port>")

        elif server_socket is None:
            print("You are not connected. Use: connect <server_ip> <port>")

        else:
            try:
                if command == "upload" and len(words) in (2, 3):
                    # if the user did not give a server name we use the name of the local file
                    server_name = words[2] if len(words) == 3 else os.path.basename(words[1])
                    upload_file(words[1], server_name)
                elif command == "download" and len(words) == 2:
                    download_file(words[1])
                elif command == "delete" and len(words) == 2:
                    run_simple_command("delete|" + words[1], words[1], "delete")
                elif command == "dir":
                    folder = words[1] if len(words) > 1 else ""
                    run_simple_command("dir|" + folder, folder or "/", "dir")
                elif command == "subfolder" and len(words) == 3:
                    run_simple_command("subfolder|%s|%s" % (words[1], words[2]),
                                       words[2], "subfolder_" + words[1])
                else:
                    print("That command is not right. Check the list at the top")
            except (ConnectionError, OSError) as error:
                # the network dropped while we were in the middle of a command
                print("Lost connection to the server:", error)
                server_socket = None

    if server_socket:
        send_message("quit")
        server_socket.close()
    stats.save_to_csv()


command_loop()
