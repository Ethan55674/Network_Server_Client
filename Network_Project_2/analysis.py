# analysis.py
# This file keeps track of how fast things are on the network.
# The server makes one of these when it starts and the client makes its own.
# DO NOT RUN THIS SERVER  IT IS AUTOMATICALLY RAN AT STARTUP
import csv
import time


class StatsCollector:
    def __init__(self, csv_filename):
        self.csv_filename = csv_filename
        # every measurement is one dictionary and they all go into this list
        # when we are done the list is saved to a csv file so we can open it in excel
        self.records = []

    def record_operation(self, user, operation, file_name, num_bytes,
                         transfer_seconds, response_seconds):
        megabytes = num_bytes / (1024 * 1024)
        # speed is megabytes divided by seconds
        # operations like dir take 0 seconds so we skip the division for them
        if transfer_seconds > 0:
            speed = megabytes / transfer_seconds
        else: # this check is for operations like DIR
            speed = 0
        record = {
            "time": time.strftime("%H:%M:%S"),
            "user_name": user,
            "operation": operation,
            "file": file_name,
            "MB": round(megabytes, 2),
            "transfer_seconds": round(transfer_seconds, 6 ),
            "MB_per_second": round(speed, 2),
            "response_seconds": round(response_seconds, 6),
        }
        self.records.append(record)

    def save_to_csv(self): # since the records need to be saved offline just storing it in a csv is the easiest way
        if len(self.records) == 0:
            return
        with open(self.csv_filename, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=self.records[0].keys())
            writer.writeheader()               # first line of the file is the column names
            writer.writerows(self.records)     # then one line for each dictionary in the list
