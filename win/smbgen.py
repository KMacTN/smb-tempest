#!/usr/bin/env python
###############################################################################
# SMB Session Generator
#
# Author:   KMac kmac@qumulo.com & Sheila (Conglomeration of AI Assistants)
# Date:     March 17th, 2025
# 
# Description:
#   This script creates multiple concurrent SMB sessions to a specified share,
#   reads files in parallel, and aggregates performance metrics such as the 
#   number of successful/failed sessions, total data read, throughput, and runtime.
#   The GUI displays live summaries and logs, and results can be exported as JSON.
#
# OS Tuning Recommendations (for Windows Server 2019):
#   To support many concurrent outbound TCP connections, consider tuning:
#     - Increase the ephemeral port range by setting "MaxUserPort" (e.g., to 65534)
#       in:
#         HKEY_LOCAL_MACHINE\SYSTEM\CurrentControlSet\Services\Tcpip\Parameters
#     - Reduce the TcpTimedWaitDelay to 30 seconds (default is often 240 seconds)
#       in the same registry key.
#     - If the GUI desktop heap becomes a bottleneck, increase the desktop heap
#       allocation in:
#         HKEY_LOCAL_MACHINE\SYSTEM\CurrentControlSet\Control\Session Manager\SubSystems\Windows
#
# Debug Logging Adjustments:
#   The smbprotocol library produces extensive debug output. This script sets the 
#   smbprotocol logger to WARNING level to reduce unnecessary logging.
#
# Usage:
#   Run this script with Python 3. For example:
#       python smb_session_generator.py --server_ip 192.168.1.100 --share_name Test \
#           --num_active_files 10 --num_inactive_sessions 5 --username user --password pass
#
# Requirements:
#   - Python 3.x
#   - Modules: argparse, concurrent.futures, datetime, json, logging, os, threading,
#     time, uuid, humanize, asyncio, tkinter, Pillow (PIL), colorama, smbprotocol
#
###############################################################################

import argparse
import concurrent.futures
import datetime
import json
import logging
import os
import threading
import time
import uuid
import humanize
import asyncio
import tkinter as tk
from tkinter import filedialog, messagebox, font as tkFont
import tkinter.ttk as ttk
import sys
from queue import Queue, Empty

from PIL import Image, ImageTk
from colorama import Fore, Style, init
import smbprotocol.exceptions
from smbprotocol.connection import Connection
from smbprotocol.open import Open
from smbprotocol.session import Session
from smbprotocol.tree import TreeConnect

init(autoreset=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)
smb_logger = logging.getLogger("smbprotocol")
smb_logger.setLevel(logging.INFO)

# Global counters and configuration variables
thread_lock = threading.Lock()
thread_counter = 0
successful_sessions = 0
failed_sessions = 0
total_data_read = 0
start_time = time.time()
debug_mode = False
update_timer_id = None
stop_threads = False
established_connections = 0

# Globals for job and session metrics
failed_session_creations = 0
job_server_ip = ""
job_share_name = ""
active_smb_sessions_count = 0
inactive_smb_sessions_count = 0

# GUI widget globals
root = None
log_text = None
start_button = None
server_ip_entry = None
share_name_entry = None
username_entry = None
password_entry = None
active_files_entry = None
inactive_sessions_entry = None
export_button = None
summary_frame = None

# Summary labels for Job Details (left) and SMB Sessions (right)
server_ip_label = None
share_name_label = None
date_label = None
run_time_label = None
data_read_label = None
throughput_label = None
total_sessions_label = None
active_sessions_label = None
inactive_sessions_label = None
failed_session_label = None

# Queue to communicate messages from background threads to the GUI
gui_queue = Queue()

# -----------------------------------------------------------------------------
# debug_print(message)
#   If debug_mode is enabled, sends a debug message to the GUI log and logger.
def debug_print(message):
    if debug_mode:
        gui_queue.put(f"[DEBUG] {message}")
        logger.debug(message)

# -----------------------------------------------------------------------------
# log_message(message)
#   Logs a message with a timestamp to both the GUI log and the logger.
def log_message(message):
    timestamp_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    full_message = f"[{timestamp_str}] {message}"
    gui_queue.put(full_message)
    logger.info(message)

# -----------------------------------------------------------------------------
# process_gui_queue()
#   Processes messages in the gui_queue and inserts them into the log_text widget.
def process_gui_queue():
    try:
        while True:
            msg = gui_queue.get_nowait()
            if log_text:
                log_text.insert(tk.END, msg + "\n")
                log_text.see(tk.END)
    except Empty:
        pass
    root.after(100, process_gui_queue)

# -----------------------------------------------------------------------------
# create_summary_gui()
#   Creates the summary frame with two sections:
#     Left: Job Details (Server IP, Share Name, Date/Time, Total Run Time, Total Data Read, Estimated Throughput)
#     Right: SMB Sessions (Successfully Created, Active Sessions, Inactive Sessions, Failed Sessions)
def create_summary_gui():
    global summary_frame, server_ip_label, share_name_label, date_label, run_time_label, data_read_label, throughput_label
    global total_sessions_label, active_sessions_label, inactive_sessions_label, failed_session_label

    frame_font = ("Segoe UI", 11, "bold")
    font_style = ("Segoe UI", 10)
    
    summary_frame = ttk.LabelFrame(root, text="Summary", padding=(10, 10))
    summary_frame.pack(padx=10, pady=5, fill=tk.X)
    
    # Left frame: Job Details
    left_frame = ttk.Frame(summary_frame)
    left_frame.grid(row=0, column=0, sticky=tk.NW, padx=(0, 20))
    
    # Right frame: SMB Sessions details
    right_frame = ttk.Frame(summary_frame)
    right_frame.grid(row=0, column=1, sticky=tk.NE)
    
    # Job Details (Left)
    ttk.Label(left_frame, text="Job Details", font=frame_font).grid(row=0, column=0, columnspan=2, sticky=tk.W, pady=(0, 5))
    
    ttk.Label(left_frame, text="Server IP:", font=font_style).grid(row=1, column=0, sticky=tk.W)
    server_ip_label = ttk.Label(left_frame, text="", font=font_style)
    server_ip_label.grid(row=1, column=1, sticky=tk.W)
    
    ttk.Label(left_frame, text="Share Name:", font=font_style).grid(row=2, column=0, sticky=tk.W)
    share_name_label = ttk.Label(left_frame, text="", font=font_style)
    share_name_label.grid(row=2, column=1, sticky=tk.W)
    
    ttk.Label(left_frame, text="Date/Time:", font=font_style).grid(row=3, column=0, sticky=tk.W)
    date_label = ttk.Label(left_frame, text="", font=font_style)
    date_label.grid(row=3, column=1, sticky=tk.W)
    
    ttk.Label(left_frame, text="Total Run Time:", font=font_style).grid(row=4, column=0, sticky=tk.W)
    run_time_label = ttk.Label(left_frame, text="", font=font_style)
    run_time_label.grid(row=4, column=1, sticky=tk.W)
    
    ttk.Label(left_frame, text="Total Data Read:", font=font_style).grid(row=5, column=0, sticky=tk.W)
    data_read_label = ttk.Label(left_frame, text="", font=font_style)
    data_read_label.grid(row=5, column=1, sticky=tk.W)
    
    ttk.Label(left_frame, text="Estimated Throughput:", font=font_style).grid(row=6, column=0, sticky=tk.W)
    throughput_label = ttk.Label(left_frame, text="", font=font_style)
    throughput_label.grid(row=6, column=1, sticky=tk.W)
    
    # SMB Sessions (Right)
    ttk.Label(right_frame, text="SMB Sessions", font=frame_font).grid(row=0, column=0, columnspan=2, sticky=tk.W, pady=(0, 5))
    
    ttk.Label(right_frame, text="Successfully Created:", font=font_style).grid(row=1, column=0, sticky=tk.W)
    total_sessions_label = ttk.Label(right_frame, text="", font=font_style)
    total_sessions_label.grid(row=1, column=1, sticky=tk.W)
    
    ttk.Label(right_frame, text="Active Sessions:", font=font_style).grid(row=2, column=0, sticky=tk.W)
    active_sessions_label = ttk.Label(right_frame, text="", font=font_style)
    active_sessions_label.grid(row=2, column=1, sticky=tk.W)
    
    ttk.Label(right_frame, text="Inactive Sessions:", font=font_style).grid(row=3, column=0, sticky=tk.W)
    inactive_sessions_label = ttk.Label(right_frame, text="", font=font_style)
    inactive_sessions_label.grid(row=3, column=1, sticky=tk.W)
    
    ttk.Label(right_frame, text="Failed Sessions:", font=font_style).grid(row=4, column=0, sticky=tk.W)
    failed_session_label = ttk.Label(right_frame, text="", font=font_style)
    failed_session_label.grid(row=4, column=1, sticky=tk.W)

# -----------------------------------------------------------------------------
# print_summary()
#   Updates all summary labels using the current global metrics.
def print_summary():
    global server_ip_label, share_name_label, date_label, run_time_label, data_read_label, throughput_label
    global total_sessions_label, active_sessions_label, inactive_sessions_label, failed_session_label
    global total_data_read, start_time, active_smb_sessions_count, inactive_smb_sessions_count, failed_session_creations, job_server_ip, job_share_name
    
    current_date = datetime.datetime.now().strftime("%A, %B %d, %Y %I:%M:%S %p")
    end_time = time.time()
    total_run_time = int(end_time - start_time)
    formatted_run_time = str(datetime.timedelta(seconds=total_run_time))
    formatted_data_read = humanize.naturalsize(total_data_read)
    throughput = total_data_read / total_run_time if total_run_time > 0 else 0
    formatted_throughput = humanize.naturalsize(throughput)
    
    # Update Job Details
    if server_ip_label:
        server_ip_label.config(text=job_server_ip)
    if share_name_label:
        share_name_label.config(text=job_share_name)
    if date_label:
        date_label.config(text=current_date)
    if run_time_label:
        run_time_label.config(text=formatted_run_time)
    if data_read_label:
        data_read_label.config(text=formatted_data_read)
    if throughput_label:
        throughput_label.config(text=f"{formatted_throughput}/s")
    
    # Update SMB Sessions details
    total_created = active_smb_sessions_count + inactive_smb_sessions_count
    if total_sessions_label:
        total_sessions_label.config(text=total_created)
    if active_sessions_label:
        active_sessions_label.config(text=active_smb_sessions_count)
    if inactive_sessions_label:
        inactive_sessions_label.config(text=inactive_smb_sessions_count)
    if failed_session_label:
        failed_session_label.config(text=failed_session_creations)

# -----------------------------------------------------------------------------
# update_summary()
#   Calls print_summary() and schedules itself to run every 3 seconds.
def update_summary():
    print_summary()
    global update_timer_id
    update_timer_id = root.after(3000, update_summary)

# -----------------------------------------------------------------------------
# cancel_summary_update()
#   Cancels the periodic summary update timer.
def cancel_summary_update():
    global update_timer_id
    if update_timer_id:
        root.after_cancel(update_timer_id)
        update_timer_id = None

# -----------------------------------------------------------------------------
# create_smb_connection(server_ip)
#   Creates and connects an SMB connection to the specified server.
def create_smb_connection(server_ip):
    debug_print(f"Creating SMB connection to: {server_ip}")
    client_guid = uuid.uuid4().bytes
    conn = Connection("smbclient", server_ip, port=445, require_signing=False)
    conn.client_guid = client_guid
    conn.connect()
    debug_print(f"SMB connection created: {conn}")
    return conn

# -----------------------------------------------------------------------------
# open_smb_file(session, conn, share_name, filename)
#   Opens an SMB file on the specified share using the provided session and connection.
# 
#   - impersonation_level=2:
#       Sets the impersonation level to "Impersonation". This allows the server to
#       perform operations using the client's credentials, which is necessary for
#       accessing resources on behalf of the client.
#   - desired_access=0x120089:
#       Specifies the combined access rights required to open and read the file.
#       This value is a bitmask that grants the necessary permissions for file I/O.
#   - file_attributes=0:
#       Indicates that no special file attributes are applied when opening the file.
#   - share_access=0x1:
#       Allows the file to be shared for read operations, preventing exclusive locks.
#   - create_disposition=0x1:
#       Specifies "FILE_OPEN", meaning the file is opened only if it already exists.
#   - create_options=0x40:
#       Indicates that the file is to be opened as a non-directory file.
def open_smb_file(session, conn, share_name, filename):
    debug_print(f"Opening SMB file: {filename} on share: {share_name}")
    tree = TreeConnect(session, f"\\\\{conn.server_name}\\{share_name}")
    tree.connect()
    file = Open(tree, filename)
    file.create(
        impersonation_level=2,
        desired_access=0x120089,
        file_attributes=0,
        share_access=0x1,
        create_disposition=0x1,
        create_options=0x40,
    )
    debug_print(f"SMB file opened: {file}")
    return tree, file

# -----------------------------------------------------------------------------
# close_smb_resources(file, tree, conn)
#   Closes the file, disconnects the tree, and disconnects the connection.
def close_smb_resources(file, tree, conn):
    debug_print("Closing SMB resources")
    file.close()
    tree.disconnect()
    conn.disconnect()
    global established_connections
    with thread_lock:
        established_connections -= 1
    debug_print("SMB resources closed")

# -----------------------------------------------------------------------------
# async_create_smb_connection(server_ip)
#   Asynchronously creates an SMB connection and updates the established_connections counter.
async def async_create_smb_connection(server_ip):
    global established_connections
    debug_print(f"Creating SMB connection to {server_ip}")
    conn = Connection("smbclient", server_ip, port=445, require_signing=False)
    conn.client_guid = uuid.uuid4().bytes
    await asyncio.to_thread(conn.connect)
    debug_print(f"SMB connection established to {server_ip}")
    with thread_lock:
        established_connections += 1
    return conn

# -----------------------------------------------------------------------------
# async_create_smb_session(conn, username, password)
#   Asynchronously creates an SMB session using the provided connection and credentials.
async def async_create_smb_session(conn, username, password):
    session = Session(conn, username, password)
    await asyncio.to_thread(session.connect)
    debug_print(f"Session created for {username}")
    return session

# -----------------------------------------------------------------------------
# async_create_smb_session_with_retry(conn, username, password, max_retries, retry_delay)
#   Attempts to create an SMB session with retries upon failure.
async def async_create_smb_session_with_retry(conn, username, password, max_retries=3, retry_delay=1):
    for attempt in range(max_retries):
        try:
            return await async_create_smb_session(conn, username, password)
        except Exception as e:
            if attempt < max_retries - 1:
                debug_print(f"Retrying session creation, attempt {attempt+1}")
                await asyncio.sleep(retry_delay)
            else:
                debug_print(f"Session creation failed: {e}")
                raise

# -----------------------------------------------------------------------------
# async_create_smb_session_pair(server_ip, username, password)
#   Asynchronously creates a pair of SMB connection and session.
async def async_create_smb_session_pair(server_ip, username, password):
    conn = await async_create_smb_connection(server_ip)
    session = await async_create_smb_session_with_retry(conn, username, password)
    return conn, session

# -----------------------------------------------------------------------------
# create_sessions_with_delay(server_ip, share_name, username, password, session_count, executor, results, launch_reads)
#   Asynchronously creates SMB sessions in batches with a delay.
#   If launch_reads is True, immediately launches file-read tasks for each new session,
#   accessing files from the "smbgen-files" subdirectory to match the initialized files.
#   Also updates the global active/inactive session counters after each batch.
async def create_sessions_with_delay(server_ip, share_name, username, password, session_count, executor, results, launch_reads=True):
    global failed_session_creations, active_smb_sessions_count, inactive_smb_sessions_count
    debug_print(f"Starting async creation of {session_count} SMB sessions for {server_ip}/{share_name}")
    sessions = []
    batch_size = 10
    for i in range(0, session_count, batch_size):
        current_batch = min(batch_size, session_count - i)
        tasks = [async_create_smb_session_pair(server_ip, username, password) for _ in range(current_batch)]
        batch_results = await asyncio.gather(*tasks, return_exceptions=True)
        new_sessions = []
        for idx, result in enumerate(batch_results, start=i):
            if isinstance(result, tuple):
                conn, session = result
                sessions.append((conn, session))
                new_sessions.append((conn, session, idx))
            else:
                failed_session_creations += 1
        # Update active or inactive session counters immediately after each batch.
        with thread_lock:
            if launch_reads:
                active_smb_sessions_count += len(new_sessions)
            else:
                inactive_smb_sessions_count += len(new_sessions)
        if launch_reads:
            for conn, session, idx in new_sessions:
                filename = f"smbgen-files/smb_snortfest.{idx}"
                executor.submit(process_file_read, conn, session, share_name, filename, results)
        # await asyncio.sleep(0.5)
    debug_print(f"All {session_count} SMB sessions processed (successful: {len(sessions)}, failed: {failed_session_creations}).")
    return sessions

# -----------------------------------------------------------------------------
# run_async_session_creation(server_ip, share_name, username, password, session_count, launch_reads)
#   Wrapper to run the async session creation in a ThreadPoolExecutor context and return sessions and results.
def run_async_session_creation(server_ip, share_name, username, password, session_count, launch_reads=True):
    if session_count <= 0:
        return [], []
    results = []  
    with concurrent.futures.ThreadPoolExecutor(max_workers=session_count) as executor:
        sessions = asyncio.run(create_sessions_with_delay(
            server_ip, share_name, username, password, session_count, executor, results, launch_reads=launch_reads
        ))
    return sessions, results

# -----------------------------------------------------------------------------
# read_smb_file_data(file, thread_id, filename, chunk_size, log_threshold)
#   Reads data from an SMB file in chunks until EOF or stop signal.
# chunk_size=64 * 1024  == 64 KiB blocksize 
# chunk_size=1024 * 1024  == 1 MiB blocksize 

def read_smb_file_data(file, thread_id, filename, chunk_size=1024 * 1024, log_threshold=1024 * 1024 * 1024):
    debug_print(f"Reading data from: {filename}")
    total_bytes = 0
    offset = 0
    last_log = 0
    while True:
        if stop_threads:
            debug_print(f"Thread {thread_id} stopping due to stop signal.")
            break
        try:
            data = file.read(offset, chunk_size)
            if not data:
                break
            with thread_lock:
                total_bytes += len(data)
                global total_data_read
                total_data_read += len(data)
                if total_data_read - last_log >= log_threshold:
                    last_log = total_data_read
            offset += len(data)
        except smbprotocol.exceptions.EndOfFile:
            break
        except Exception as e:
            debug_print(f"Unexpected error: {e}")
            raise
    debug_print(f"Finished reading data from: {filename}, total bytes: {total_bytes}")
    return total_bytes

# -----------------------------------------------------------------------------
# process_file_read(conn, session, share_name, filename, results)
#   Processes reading a file from an SMB session; logs success or errors.
def process_file_read(conn, session, share_name, filename, results):
    global thread_counter, successful_sessions, failed_sessions
    with thread_lock:
        thread_id = thread_counter
        thread_counter += 1
    try:
        debug_print(f"Thread {thread_id} processing file: {filename}")
        log_message(f"[Thread {thread_id}] Opening \"{filename}\"")
        tree, file = open_smb_file(session, conn, share_name, filename)
        log_message(f"[Thread {thread_id}] Successfully opened \"{filename}\". Starting read...")
        total_bytes = read_smb_file_data(file, thread_id, filename)
        close_smb_resources(file, tree, conn)
        with thread_lock:
            results.append(f"[Thread {thread_id}] Finished reading \"{filename}\" ({total_bytes / (1024 * 1024):.2f} MiB)")
            successful_sessions += 1
        debug_print(f"Thread {thread_id} finished processing file: {filename}")
    except Exception as e:
        import traceback
        traceback.print_exc()
        error_msg = str(e)
        if "EndOfFile" in error_msg:
            with thread_lock:
                results.append(f"[Thread {thread_id}] Reached EOF for {Fore.YELLOW}{filename} (bytes read: {total_bytes}).{Fore.RESET}")
                log_message(f"[Thread {thread_id}] Reached EOF for {filename} (bytes read: {total_bytes}).")
        else:
            with thread_lock:
                results.append(f"{Fore.RED}[Thread {thread_id}] Error reading {Fore.YELLOW}{filename}{Fore.RESET}: {error_msg}")
                log_message(f"[Thread {thread_id}] Error reading {filename}: {error_msg}")
            with thread_lock:
                failed_sessions += 1
        debug_print(f"Thread {thread_id} encountered error processing file: {filename}, error: {error_msg}")

# -----------------------------------------------------------------------------
# initialize_files()
#   Creates test files for SMB operations.
#   - The base directory is constructed using the Server IP and Share Name input fields,
#     appending the "files" subdirectory. The resulting UNC path is of the form:
#         "\\\\<server_ip>\\<share_name>\\files"
#   - The number of files is determined by adding the values from the "Active Files" and
#     "Inactive Sessions" input fields.
#   - Each file is 125 MiB in size. Each file is pre-allocated by seeking to (file_size - 1)
#     and writing a single null byte.
def initialize_files():
    try:
        server_ip = server_ip_entry.get().strip()
        share_name = share_name_entry.get().strip()
        # Construct the base UNC path with the "files" subdirectory.
        directory = f"\\\\{server_ip}\\{share_name}\\smbgen-files"
        active = int(active_files_entry.get())
        inactive = int(inactive_sessions_entry.get())
        num_files = active + inactive
    except Exception as e:
        log_message(f"{Fore.RED}Error reading input fields for file initialization: {e}{Fore.RESET}")
        return

    file_size = 125 * 1024 * 1024  # 125 MiB

    if not os.path.exists(directory):
        try:
            os.makedirs(directory)
            log_message(f"Directory created: {directory}")
        except Exception as e:
            log_message(f"{Fore.RED}Error creating directory {directory}: {e}{Fore.RESET}")
            return

    for i in range(num_files):
        filename = directory.rstrip("\\") + "\\" + f"smb_snortfest.{i}"
        try:
            with open(filename, "wb") as f:
                f.seek(file_size - 1)
                f.write(b'\0')
            log_message(f"Created file: {filename}")
        except Exception as e:
            log_message(f"{Fore.RED}Error creating file {filename}: {e}{Fore.RESET}")
    log_message("File initialization complete.")

# -----------------------------------------------------------------------------
# connect_and_read(server_ip, share_name, username, password, num_active_files, num_inactive_sessions)
#   Establishes active and inactive SMB sessions, launches file reading for active sessions,
#   updates global job/session metrics, logs a final summary, and leaves summary updates running.
def connect_and_read(server_ip, share_name, username, password, num_active_files, num_inactive_sessions):
    global start_button, stop_threads, job_server_ip, job_share_name, active_smb_sessions_count, inactive_smb_sessions_count
    stop_threads = False
    job_server_ip = server_ip
    job_share_name = share_name

    with thread_lock:
        log_message(f"[Session Setup] Creating {num_active_files + num_inactive_sessions} SMB sessions on: \"{server_ip}/{share_name}\"")
    
    active_sessions, active_results = run_async_session_creation(server_ip, share_name, username, password, num_active_files, launch_reads=True)
    inactive_sessions, _ = run_async_session_creation(server_ip, share_name, username, password, num_inactive_sessions, launch_reads=False)
    
    # Final update with the complete session counts.
    with thread_lock:
        active_smb_sessions_count = len(active_sessions)
        inactive_smb_sessions_count = len(inactive_sessions)
    
    with thread_lock:
        for result in active_results:
            log_message(result)
    
    final_summary = f"Successfully Completed: {len(active_sessions)} Active and {len(inactive_sessions)} Inactive SMB Sessions"
    log_message(final_summary)
    
    start_button.config(state=tk.NORMAL, text="Start")
    # Continue updating summary every 3 seconds.
    print_summary()
    if export_button:
        export_button.config(state=tk.NORMAL)
    return active_sessions, inactive_sessions

# -----------------------------------------------------------------------------
# stop_smb_operations()
#   Signals background threads to stop, cancels summary updates, and resets the Start button.
def stop_smb_operations():
    global stop_threads, start_button
    stop_threads = True
    start_button.config(state=tk.DISABLED, text="Stopping...")
    cancel_summary_update()
    def reset_start_button():
        start_button.config(state=tk.NORMAL, text="Start", command=start_smb_operations)
    root.after(1000, reset_start_button)

# -----------------------------------------------------------------------------
# start_smb_operations()
#   Initiates an SMB operation run by reading input fields, resetting global counters,
#   scheduling summary updates, and starting the background job in a new thread.
def start_smb_operations():
    global stop_threads, start_button, server_ip_entry, share_name_entry, username_entry, password_entry
    global active_files_entry, inactive_sessions_entry, successful_sessions, failed_sessions, total_data_read, start_time, update_timer_id
    global failed_session_creations, active_smb_sessions_count, inactive_smb_sessions_count
    stop_threads = False
    def run_smb_operations():
        try:
            server_ip = server_ip_entry.get()
            share_name = share_name_entry.get()
            username = username_entry.get()
            password = password_entry.get()
            try:
                num_active_files = int(active_files_entry.get())
                num_inactive_sessions = int(inactive_sessions_entry.get())
            except ValueError:
                log_message(f"{Fore.RED}Error: Invalid input for number of active files or inactive sessions.{Fore.RESET}")
                start_button.config(state=tk.NORMAL, text="Start")
                return
            if not username or not password:
                log_message(f"{Fore.RED}Error: Username and password must be provided.{Fore.RESET}")
                start_button.config(state=tk.NORMAL, text="Start")
                return
            with thread_lock:
                successful_sessions = 0
                failed_sessions = 0
                total_data_read = 0
                failed_session_creations = 0
                active_smb_sessions_count = 0
                inactive_smb_sessions_count = 0
                start_time = time.time()
            update_timer_id = root.after(3000, update_summary)
            connect_and_read(server_ip, share_name, username, password, num_active_files, num_inactive_sessions)
        except Exception as e:
            log_message(f"{Fore.RED}An unexpected error occurred: {e}{Fore.RESET}")
            start_button.config(state=tk.NORMAL, text="Start")
            import traceback
            traceback.print_exc()
    start_button.config(state=tk.NORMAL, text="Stop", command=stop_smb_operations)
    threading.Thread(target=run_smb_operations).start()

# -----------------------------------------------------------------------------
# create_icon(parent)
#   Loads and displays an icon image in the specified parent widget.
def create_icon(parent):
    image_path = "smbgen-icon.png"
    if hasattr(sys, '_MEIPASS'):
        image_path = os.path.join(sys._MEIPASS, "smbgen-icon.png")
    if not os.path.exists(image_path):
        print(f"Error: Icon file not found at {image_path}")
        return
    image = Image.open(image_path)
    image = image.resize((300, 300), Image.LANCZOS)
    icon = ImageTk.PhotoImage(image)
    icon_label = tk.Label(parent, image=icon)
    icon_label.image = icon
    icon_label.grid(row=0, column=2, rowspan=6, padx=50, pady=10, sticky="nsew")
    parent.grid_columnconfigure(2, weight=1)

# -----------------------------------------------------------------------------
# export_results()
#   Exports the current job and session metrics along with the log messages to a JSON file.
def export_results():
    results = {
        "date": date_label.cget("text") if date_label else "",
        "successful_sessions": successful_sessions,
        "failed_sessions": failed_sessions,
        "total_data_read": total_data_read,
        "throughput": throughput_label.cget("text") if throughput_label else "",
        "total_run_time": run_time_label.cget("text") if run_time_label else "",
        "active_smb_sessions": active_smb_sessions_count,
        "inactive_smb_sessions": inactive_smb_sessions_count,
        "failed_session_creations": failed_session_creations,
        "log_messages": log_text.get("1.0", tk.END).strip().split("\n"),
        "established_connections": established_connections,
    }
    file_path = filedialog.asksaveasfilename(
        defaultextension=".json",
        filetypes=[("JSON files", "*.json"), ("All Files", "*.*")],
        title="Save Results"
    )
    if file_path:
        with open(file_path, "w") as f:
            json.dump(results, f, indent=4)
        log_message(f"Results exported to {file_path}")

# -----------------------------------------------------------------------------
# main()
#   Initializes the GUI, processes command-line arguments, and starts the main Tkinter loop.
def main():
    global root, log_text, start_button, export_button
    global server_ip_entry, share_name_entry, username_entry, password_entry
    global active_files_entry, inactive_sessions_entry, debug_mode

    if hasattr(sys, 'frozen'):
        warning_message = (
            "Before running this application, please ensure you have:\n"
            "- Disabled/Removed Windows Defender Antivirus (or similar).\n"
            "- Disabled the local Firewall.\n"
            "- Network access to the Network Storage is available.\n"
            "Click OK to continue, or Cancel to exit."
        )
        result = messagebox.askokcancel("Prerequisite Warning", warning_message)
        if not result:
            sys.exit()

    root = tk.Tk()
    root.title("SMB Session Generator")
    font_style = ("Segoe UI", 10)
    frame_font = ("Segoe UI", 12, "bold")

    input_frame = ttk.LabelFrame(root, text="Input", padding=(10, 10))
    input_frame.pack(padx=10, pady=5, fill=tk.X)
    input_frame.configure(labelwidget=ttk.Label(input_frame, text="Input", font=frame_font))
    create_icon(input_frame)

    ttk.Label(input_frame, text="Server IP:", font=font_style).grid(row=0, column=0, sticky=tk.W, padx=5, pady=2)
    server_ip_entry = ttk.Entry(input_frame, width=30, font=font_style)
    server_ip_entry.grid(row=0, column=1, sticky=tk.W, padx=5, pady=2)

    ttk.Label(input_frame, text="Share Name:", font=font_style).grid(row=1, column=0, sticky=tk.W, padx=5, pady=2)
    share_name_entry = ttk.Entry(input_frame, width=30, font=font_style)
    share_name_entry.grid(row=1, column=1, sticky=tk.W, padx=5, pady=2)

    ttk.Label(input_frame, text="Username:", font=font_style).grid(row=2, column=0, sticky=tk.W, padx=5, pady=2)
    username_entry = ttk.Entry(input_frame, width=30, font=font_style)
    username_entry.grid(row=2, column=1, sticky=tk.W, padx=5, pady=2)

    ttk.Label(input_frame, text="Password:", font=font_style).grid(row=3, column=0, sticky=tk.W, padx=5, pady=2)
    password_entry = ttk.Entry(input_frame, width=30, show="*", font=font_style)
    password_entry.grid(row=3, column=1, sticky=tk.W, padx=5, pady=2)

    ttk.Label(input_frame, text="Active Files:", font=font_style).grid(row=4, column=0, sticky=tk.W, padx=5, pady=2)
    active_files_entry = ttk.Entry(input_frame, width=10, font=font_style)
    active_files_entry.grid(row=4, column=1, sticky=tk.W, padx=5, pady=2)

    ttk.Label(input_frame, text="Inactive Sessions:", font=font_style).grid(row=5, column=0, sticky=tk.W, padx=5, pady=2)
    inactive_sessions_entry = ttk.Entry(input_frame, width=10, font=font_style)
    inactive_sessions_entry.grid(row=5, column=1, sticky=tk.W, padx=5, pady=2)
    inactive_sessions_entry.insert(0, "0")

    button_frame = ttk.Frame(root, padding=(10, 5))
    button_frame.pack(padx=10, pady=5, fill=tk.X)
    button_font = ("Segoe UI", 12, "bold")
    style = ttk.Style()
    style.configure("Large.TButton", font=button_font)
    start_button = ttk.Button(button_frame, text="Start", command=start_smb_operations, style="Large.TButton")
    start_button.pack(side=tk.LEFT, padx=5)
    # New "Initialize Files" button added here. It starts the file creation process in a background thread.
    init_button = ttk.Button(button_frame, text="Initialize Files",
                             command=lambda: threading.Thread(target=initialize_files, daemon=True).start(),
                             style="Large.TButton")
    init_button.pack(side=tk.LEFT, padx=5)

    log_frame = ttk.LabelFrame(root, text="Log", padding=(10, 5))
    log_frame.pack(padx=10, pady=5, fill=tk.BOTH, expand=True)
    log_frame.configure(labelwidget=ttk.Label(log_frame, text="Log", font=frame_font))
    log_text = tk.Text(log_frame, wrap=tk.WORD, height=10, state=tk.NORMAL, font=font_style)
    log_text.pack(fill=tk.BOTH, expand=True)

    export_button = ttk.Button(root, text="Export Results", command=export_results, style="Large.TButton")
    export_button.pack(padx=10, pady=5, anchor="e")
    export_button.config(state=tk.DISABLED)

    parser = argparse.ArgumentParser(
        description="Connect to an SMB share with multiple connections and read files in parallel."
    )
    parser.add_argument("--server_ip", help="Server IP address")
    parser.add_argument("--share_name", help="Share name")
    parser.add_argument("--num_active_files", type=int, help="Number of active files to read")
    parser.add_argument("--num_inactive_sessions", type=int, help="Number of inactive sessions to create")
    parser.add_argument("--username", help="Username for SMB authentication")
    parser.add_argument("--password", help="Password for SMB authentication")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    args = parser.parse_args()

    if args.server_ip:
        server_ip_entry.insert(0, args.server_ip)
    if args.share_name:
        share_name_entry.insert(0, args.share_name)
    if args.num_active_files:
        active_files_entry.insert(0, args.num_active_files)
    if args.num_inactive_sessions:
        inactive_sessions_entry.insert(0, args.num_inactive_sessions)
    if args.username:
        username_entry.insert(0, args.username)
    if args.password:
        password_entry.insert(0, args.password)

    if args.debug:
        debug_mode = True
    else:
        root_logger = logging.getLogger()
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)
        logging.basicConfig(level=logging.INFO,
                            format="%(asctime)s [%(levelname)s] %(message)s")
        logging.getLogger("smbprotocol").setLevel(logging.WARNING)
        logging.getLogger("smbprotocol.connection").setLevel(logging.WARNING)
        logging.getLogger("smbprotocol.session").setLevel(logging.WARNING)
        logging.getLogger("smbprotocol.tree").setLevel(logging.WARNING)
        logging.disable(logging.DEBUG)

    create_summary_gui()
    print_summary() 
    process_gui_queue()
    root.mainloop()

if __name__ == "__main__":
    main()