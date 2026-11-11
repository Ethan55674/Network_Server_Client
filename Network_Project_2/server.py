# server.py
# run it with   python server.py
#
# When the server starts it waits for clients to connect
# Every client gets its own thread so many clients can use the server at once
# Each thread logs the client in and then keeps reading commands from them
#
# Messages are sent as 4 bytes that say how long the text is and then the text
# Commands look like   upload|docs/a.txt
# Replies start with OK or ERROR
# Files are sent as the size first and then the file data in small pieces
import hashlib
import os
import socket
import threading
import time
from analysis import StatsCollector

PORT = 5000
STORAGE_FOLDER = "server_storage"
CHUNK_SIZE = 64 * 1024   # files are sent in 64 KB pieces so a 2 GB file never has to fit in memory

# Users
# we only keep the hash of each password not the real one
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()


USER_PASSWORD_HASHES = {
    "Ethan": hash_password("pass123"), # use these examples to login from the client side
    "Bruno": hash_password("pass456"),
}

stats = StatsCollector("server_stats.csv")
files_in_use = set()  # names of files that are being sent or received right now
file_counter_lock = threading.Lock()
file_counter = 0  # as the name implies how many files are in the server


# Sending and receiving
def send_message(connection, text):
    data = text.encode()
    connection.sendall(len(data).to_bytes(4, "big") + data)


def receive_exact_bytes(connection, how_many):
    # recv can give us less than we asked for
    # so this loop keeps calling it until we have all the bytes we need
    data = b""
    while len(data) < how_many:
        piece = connection.recv(how_many - len(data))
        if not piece:
            # this gives an error in case a client stops transmitting in the middle of a file transfer
            raise ConnectionError("client disconnected")
        data += piece
    return data


def receive_message(connection):
    length = int.from_bytes(receive_exact_bytes(connection, 4), "big")
    return receive_exact_bytes(connection, length).decode()


def send_file_data(connection, file_path):
    send_message(connection, str(os.path.getsize(file_path)))
    with open(file_path, "rb") as f:
        # read one piece of the file at a time and send it until there is nothing left
        while True:
            piece = f.read(CHUNK_SIZE)
            if not piece:
                break
            connection.sendall(piece)


def receive_file_data(connection, save_path):
    total_size = int(receive_message(connection))
    received = 0
    with open(save_path, "wb") as f:
        # keep receiving pieces and writing them until we have the whole file
        while received < total_size:
            amount = min(CHUNK_SIZE, total_size - received)
            f.write(receive_exact_bytes(connection, amount))
            received += amount
    return total_size


# File names
def make_logical_name(original_path):
    # the stored name starts with a letter for the type then S for server then a number
    # T is text and A is audio and V is video and O is anything else
    # so a text file called notes.txt gets saved as TS001_notes.txt
    global file_counter
    original_name = os.path.basename(original_path)
    extension = os.path.splitext(original_name)[1].lower()
    #txt check
    if extension in (".txt", ".csv", ".log"):
        type_letter = "T"
    elif extension in (".wav", ".mp3"):
        #audio check
        type_letter = "A"
    #video check
    elif extension in (".mp4", ".avi", ".mov"):
        type_letter = "V"
    else:
        type_letter = "O"

    # the lock makes sure two threads can never get the same number
    with file_counter_lock:
        file_counter += 1
        number = file_counter
    return "%sS%03d_%s" % (type_letter, number, original_name)


def find_stored_file(client_path):
    # the client asks for a.txt but on the disk it is saved as TS001_a.txt
    # so we look through the folder for a file whose name after the underscore is a.txt
    folder = os.path.join(STORAGE_FOLDER, os.path.dirname(client_path))
    original_name = os.path.basename(client_path)
    if os.path.isdir(folder):
        for stored_name in os.listdir(folder):
            if "_" in stored_name and stored_name.split("_", 1)[1] == original_name:
                return os.path.join(folder, stored_name)
    return None


# Commands
# start_time is when the command arrived and we use it to work out the response time
def handle_upload_command(connection, user, client_path, start_time):
    if not os.path.isdir(os.path.join(STORAGE_FOLDER, os.path.dirname(client_path))):
        send_message(connection, "ERROR That folder does not exist")
        return
    if client_path in files_in_use:
        send_message(connection, "ERROR That file is being used right now")
        return

    existing_file = find_stored_file(client_path)
    if existing_file:
        # the file is already on the server so we ask the client if we should overwrite it
        send_message(connection, "EXISTS")
        response_seconds = time.time() - start_time
        if receive_message(connection) != "yes":
            return    # client said no so there is nothing more to do
        save_path = existing_file
    else:
        send_message(connection, "OK")
        response_seconds = time.time() - start_time
        save_path = os.path.join(STORAGE_FOLDER, os.path.dirname(client_path),
                                 make_logical_name(client_path))

    files_in_use.add(client_path)
    try:
        transfer_start = time.time()
        num_bytes = receive_file_data(connection, save_path)
        transfer_seconds = time.time() - transfer_start
        send_message(connection, "OK Uploaded as " + os.path.basename(save_path))
        stats.record_operation(user, "upload", client_path, num_bytes,
                               transfer_seconds, response_seconds)
    finally:
        # finally always runs even if the upload crashed
        # this way the file never stays marked as in use forever
        files_in_use.discard(client_path)


def handle_download_command(connection, user, client_path, start_time):
    stored_file = find_stored_file(client_path)
    if not stored_file:
        send_message(connection, "ERROR File does not exist")
        return

    files_in_use.add(client_path)
    try:
        send_message(connection, "OK")
        response_seconds = time.time() - start_time
        transfer_start = time.time()
        send_file_data(connection, stored_file)
        stats.record_operation(user, "download", client_path, os.path.getsize(stored_file),
                               time.time() - transfer_start, response_seconds)
    finally:
        files_in_use.discard(client_path)


def handle_delete_command(connection, user, client_path, start_time):
    stored_file = find_stored_file(client_path)
    if not stored_file:
        send_message(connection, "ERROR File does not exist")
    elif client_path in files_in_use:
        send_message(connection, "ERROR File is being used right now so it cannot be deleted")
    else:
        os.remove(stored_file)
        send_message(connection, "OK Deleted " + client_path)
        stats.record_operation(user, "delete", client_path, 0, 0, time.time() - start_time)


def handle_dir_command(connection, user, folder_path, start_time):
    full_folder = os.path.join(STORAGE_FOLDER, folder_path)
    if not os.path.isdir(full_folder):
        send_message(connection, "ERROR Folder does not exist")
        return

    lines = []
    # go through everything in the folder and make one line for each one
    for name in sorted(os.listdir(full_folder)):
        if os.path.isdir(os.path.join(full_folder, name)):
            lines.append("[FOLDER] " + name)
        else:
            lines.append("[FILE] " + name)    # shows the stored name like TS001_a.txt
    if len(lines) == 0:
        lines.append("(empty)")
    send_message(connection, "OK " + "\n".join(lines))
    stats.record_operation(user, "dir", folder_path or "/", 0, 0, time.time() - start_time)


def handle_subfolder_command(connection, user, action, folder_path, start_time):
    full_folder = os.path.join(STORAGE_FOLDER, folder_path)

    if action == "create":
        if os.path.exists(full_folder):
            send_message(connection, "ERROR Folder already exists")
            return
        os.makedirs(full_folder)
        send_message(connection, "OK Created folder " + folder_path)
    elif action == "delete":
        if not os.path.isdir(full_folder):
            send_message(connection, "ERROR Folder does not exist")
            return
        if len(os.listdir(full_folder)) > 0:
            send_message(connection, "ERROR Folder is not empty")
            return
        os.rmdir(full_folder)
        send_message(connection, "OK Deleted folder " + folder_path)
    else:
        send_message(connection, "ERROR Use subfolder create or subfolder delete")
        return
    stats.record_operation(user, "subfolder_" + action, folder_path, 0, 0, time.time() - start_time)


# Login
def login_client(connection):
    # the first message from a client is the username and the password hash
    # we check the hash against the one we saved
    username, password_hash = receive_message(connection).split(" ")
    if USER_PASSWORD_HASHES.get(username) == password_hash:
        send_message(connection, "OK")
        return username
    send_message(connection, "ERROR Wrong username or password")
    return None


# One client
# every connected client runs this function in its own thread
def handle_one_client(connection, address):
    print("Client connected:", address)
    try:
        user = login_client(connection)
        if user is None:
            return
        print(user, "logged in")

        # this loop keeps reading commands from the client
        # it only stops when the client sends quit
        while True:
            parts = receive_message(connection).split("|")    # for example ["upload", "a.txt"]
            start_time = time.time()
            command = parts[0]

            if command == "upload":
                handle_upload_command(connection, user, parts[1], start_time)
            elif command == "download":
                handle_download_command(connection, user, parts[1], start_time)
            elif command == "delete":
                handle_delete_command(connection, user, parts[1], start_time)
            elif command == "dir":
                handle_dir_command(connection, user, parts[1], start_time)
            elif command == "subfolder":
                handle_subfolder_command(connection, user, parts[1], parts[2], start_time)
            elif command == "quit":
                break
            else:
                send_message(connection, "ERROR Unknown command")
    except (ConnectionError, OSError):
        # this happens when the client closes the program or the network drops
        # ConnectionError comes from our receive function and OSError is any other socket problem
        # we catch them here so one bad client does not crash the server
        print("Lost connection with", address)
    finally:
        connection.close()
        print("Client disconnected:", address)


# Start the server
def start_server():
    os.makedirs(STORAGE_FOLDER, exist_ok=True)

    # AF_INET means IPv4 and SOCK_STREAM means TCP
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    # without this line you get an Address already in use error if you restart the server quickly
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind(("0.0.0.0", PORT))    # 0.0.0.0 means listen on every network the computer is on
    server_socket.listen()
    print("Server running on port", PORT, "- press Ctrl+C to stop")

    try:
        # this loop never ends by itself
        # accept waits until a client connects and then we give that client a thread
        while True:
            connection, address = server_socket.accept()
            threading.Thread(target=handle_one_client, args=(connection, address)).start()
    except KeyboardInterrupt:
        # Ctrl+C lands here so we can save the statistics before closing
        pass
    stats.save_to_csv()
    server_socket.close()


start_server()
