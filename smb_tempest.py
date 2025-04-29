#!/usr/bin/env python3
"""
Name:   smb_tempest.py
Author: KMac and Sheila
Date:   April 28th, 2025

Unleash the storm on your SMB server.

Description:
------------
smb_tempest.py is a multi-threaded SMB session generator and load tester.
It connects to an SMB share, creates client-specific directories,
writes large files, performs sequential reads, spawns and deletes
many small random files, and measures performance throughout.

Example Usage:
--------------
python smb_tempest.py \
    --server_ip 192.168.1.100 \
    --share_name myshare \
    --username myuser \
    --password mypass \
    --num_tasks 100 \
    --max_file_size 512
"""

import argparse
import concurrent.futures
import logging
import os
import random
import time
import uuid
import struct
import functools
import traceback
from datetime import datetime

from smbprotocol.connection import Connection
from smbprotocol.session import Session
from smbprotocol.tree import TreeConnect
from smbprotocol.open import (
    Open,
    ImpersonationLevel,
    FilePipePrinterAccessMask,
    FileAttributes,
    ShareAccess,
    CreateDisposition,
    CreateOptions,
)
from smbprotocol.file_info import FileStandardInformation

MAX_FILE_SIZE = 512
SMB_BLOCK_SIZE = 1024 * 1024  # 1 MiB

def retry_operation(max_attempts=3, delay_seconds=1):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if logging.getLogger().isEnabledFor(logging.DEBUG):
                        logging.debug(f"Retryable exception in {func.__name__} (attempt {attempt + 1}): {e}")
                        traceback.print_exc()
                    if attempt < max_attempts - 1:
                        time.sleep(delay_seconds)
                    else:
                        raise
        return wrapper
    return decorator

def setup_logging(debug=False):
    logs_dir = "logs"
    os.makedirs(logs_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = os.path.join(logs_dir, f"smb_tempest_{timestamp}.log")

    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG if debug else logging.INFO)
    logging.getLogger("smbprotocol").setLevel(logging.WARNING)

    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    file_handler = logging.FileHandler(log_file)
    file_formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)

    class DotStreamHandler(logging.StreamHandler):
        def emit(self, record):
            self.stream.write(".")
            self.flush()

    logger.addHandler(DotStreamHandler())
    logging.info(f"Logging initialized. Log file: {log_file}")

def get_client_uuid():
    uuid_file = "client_uuid.txt"
    if os.path.exists(uuid_file):
        with open(uuid_file, "r") as f:
            stored_uuid = f.read().strip()
            if stored_uuid:
                return stored_uuid
    new_uuid = str(uuid.uuid4())
    with open(uuid_file, "w") as f:
        f.write(new_uuid)
    return new_uuid

def smb_get_file_size(tree, remote_file_path):
    attempts = 0
    max_attempts = 10
    while attempts < max_attempts:
        try:
            file = Open(tree, remote_file_path)
            file.create(
                impersonation_level=ImpersonationLevel.Impersonation,
                desired_access=FilePipePrinterAccessMask.FILE_READ_ATTRIBUTES,
                file_attributes=FileAttributes.FILE_ATTRIBUTE_NORMAL,
                share_access=ShareAccess.FILE_SHARE_READ,
                create_disposition=CreateDisposition.FILE_OPEN,
                create_options=CreateOptions.FILE_NON_DIRECTORY_FILE,
            )
            size = file.end_of_file
            file.close()
            return size
        except Exception as e:
            logging.warning(f"File size check attempt {attempts + 1}/10 failed: {e}")
            time.sleep(0.5)
            attempts += 1
    logging.error(f"Failed to verify file size after {max_attempts} attempts.")
    return 0

@retry_operation(max_attempts=5, delay_seconds=2)
def smb_create_file(tree, remote_file_path, size):
    file = Open(tree, remote_file_path)
    file.create(
        impersonation_level=ImpersonationLevel.Impersonation,
        desired_access=FilePipePrinterAccessMask.GENERIC_READ | FilePipePrinterAccessMask.GENERIC_WRITE,
        file_attributes=FileAttributes.FILE_ATTRIBUTE_NORMAL,
        share_access=ShareAccess.FILE_SHARE_READ | ShareAccess.FILE_SHARE_WRITE,
        create_disposition=CreateDisposition.FILE_OVERWRITE_IF,
        create_options=CreateOptions.FILE_NON_DIRECTORY_FILE,
    )
    total_written = 0
    buffer = os.urandom(SMB_BLOCK_SIZE)
    target_size = size
    while total_written < target_size:
        to_write = min(SMB_BLOCK_SIZE, target_size - total_written)
        file.write(buffer[:to_write], total_written)
        total_written += to_write
    file.flush()
    file.close()
    time.sleep(1)
    verified_size = smb_get_file_size(tree, remote_file_path)
    if verified_size < target_size * 0.9:
        raise Exception(f"File size mismatch: expected {target_size}, got {verified_size}")
    else:
        logging.info(f"File {remote_file_path} successfully written ({verified_size} bytes)")

@retry_operation(max_attempts=5, delay_seconds=2)
def smb_read_file(session, server_ip, share_name, remote_file_path):
    time.sleep(1)
    tree = TreeConnect(session, f"\\\\{server_ip}\\{share_name}")
    tree.connect()
    file = Open(tree, remote_file_path)
    file.create(
        impersonation_level=ImpersonationLevel.Impersonation,
        desired_access=FilePipePrinterAccessMask.GENERIC_READ,
        file_attributes=FileAttributes.FILE_ATTRIBUTE_NORMAL,
        share_access=ShareAccess.FILE_SHARE_READ,
        create_disposition=CreateDisposition.FILE_OPEN,
        create_options=CreateOptions.FILE_NON_DIRECTORY_FILE,
    )
    total_bytes = 0
    offset = 0
    try:
        while True:
            try:
                data = file.read(offset, SMB_BLOCK_SIZE)
                if not data:
                    break
                total_bytes += len(data)
                offset += len(data)
            except Exception as e:
                if "STATUS_END_OF_FILE" in str(e) or "0xc0000011" in str(e):
                    break
                else:
                    raise
    finally:
        file.close()
        tree.disconnect()
    return total_bytes

@retry_operation(max_attempts=5, delay_seconds=2)
def smb_create_random_file(tree, remote_file_path):
    file = Open(tree, remote_file_path)
    file.create(
        impersonation_level=ImpersonationLevel.Impersonation,
        desired_access=FilePipePrinterAccessMask.GENERIC_WRITE,
        file_attributes=FileAttributes.FILE_ATTRIBUTE_NORMAL,
        share_access=ShareAccess.FILE_SHARE_READ | ShareAccess.FILE_SHARE_WRITE,
        create_disposition=CreateDisposition.FILE_OVERWRITE_IF,
        create_options=CreateOptions.FILE_NON_DIRECTORY_FILE,
    )
    file.write(b'\0' * 4096, 0)
    file.close()

def smb_delete_file(session, server_ip, share_name, remote_file_path):
    try:
        tree = TreeConnect(session, f"\\\\{server_ip}\\{share_name}")
        tree.connect()
        file = Open(tree, remote_file_path)
        file.create(
            impersonation_level=ImpersonationLevel.Impersonation,
            desired_access=FilePipePrinterAccessMask.DELETE,
            file_attributes=FileAttributes.FILE_ATTRIBUTE_NORMAL,
            share_access=ShareAccess.FILE_SHARE_DELETE,
            create_disposition=CreateDisposition.FILE_OPEN,
            create_options=CreateOptions.FILE_NON_DIRECTORY_FILE | CreateOptions.FILE_DELETE_ON_CLOSE,
        )
        file.close()
        tree.disconnect()
    except Exception as e:
        logging.warning(f"Failed to delete file {remote_file_path}: {e}")

def ensure_directory_exists(tree, directory_name):
    try:
        directory = Open(tree, directory_name)
        directory.create(
            impersonation_level=ImpersonationLevel.Impersonation,
            desired_access=FilePipePrinterAccessMask.GENERIC_READ | FilePipePrinterAccessMask.GENERIC_WRITE,
            file_attributes=FileAttributes.FILE_ATTRIBUTE_DIRECTORY,
            share_access=ShareAccess.FILE_SHARE_READ | ShareAccess.FILE_SHARE_WRITE,
            create_disposition=CreateDisposition.FILE_OPEN_IF,
            create_options=CreateOptions.FILE_DIRECTORY_FILE,
        )
        directory.close()
    except Exception as e:
        logging.error(f"Error ensuring directory '{directory_name}' exists: {e}")

def process_task(task_id, server_ip, share_name, username, password, client_uuid):
    try:
        logging.info(f"[Task {task_id}] Starting task on {server_ip} for share '{share_name}'")
        conn = Connection("smbclient", server_ip, port=445, require_signing=False)
        conn.client_guid = uuid.uuid4().bytes
        conn.connect()
        session = Session(conn, username, password)
        session.connect()
        tree = TreeConnect(session, f"\\\\{server_ip}\\{share_name}")
        tree.connect()
        client_dir = client_uuid
        ensure_directory_exists(tree, client_dir)
        remote_file_path = f"{client_dir}\\smb_tempest.{task_id}"
        smb_create_file(tree, remote_file_path, MAX_FILE_SIZE * 1024**2)
        bytes_read = smb_read_file(session, server_ip, share_name, remote_file_path)
        random_files = []
        for seq in range(random.randint(10, 100)):
            random_file = f"{client_dir}\\{seq}_randomfile.{task_id}"
            smb_create_random_file(tree, random_file)
            random_files.append(random_file)
        for random_file in random_files:
            smb_delete_file(session, server_ip, share_name, random_file)
        tree.disconnect()
        session.disconnect()
        conn.disconnect()
        return {
            "bytes_read": bytes_read,
            "num_random_files": len(random_files),
        }
    except Exception as e:
        logging.error(f"[Task {task_id}] Exception: {e}")
        if logging.getLogger().isEnabledFor(logging.DEBUG):
            traceback.print_exc()
        return {}

def print_summary(task_stats_list, elapsed_time):
    total_tasks = len(task_stats_list)
    total_bytes = sum(stats.get("bytes_read", 0) for stats in task_stats_list)
    total_files = sum(stats.get("num_random_files", 0) for stats in task_stats_list)
    throughput = (total_bytes / 1024**2) / elapsed_time if elapsed_time > 0 else 0
    print(f"""
================== Test Summary ==================
Total Tasks Executed       : {total_tasks}
Total Random Files Created : {total_files}
Total Bytes Read           : {total_bytes} bytes ({total_bytes/1024/1024:.2f} MB)
Total Time Taken           : {elapsed_time:.2f} seconds
Overall Throughput         : {throughput:.2f} MB/s
==================================================
""")
    if total_bytes == 0:
        print("⚠️ Warning: No bytes read! Check server visibility or permissions.")

def main():
    global MAX_FILE_SIZE
    parser = argparse.ArgumentParser(description="SMB Session Generator (Tempest Edition)")
    parser.add_argument("--server_ip", required=True)
    parser.add_argument("--share_name", required=True)
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--num_tasks", type=int, default=1)
    parser.add_argument("--max_file_size", type=int, default=1024)
    parser.add_argument("--debug", action="store_true", help="Enable debug-level logging")
    args = parser.parse_args()
    setup_logging(debug=args.debug)
    MAX_FILE_SIZE = args.max_file_size
    client_uuid = get_client_uuid()
    task_stats_list = []
    start_time = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.num_tasks) as executor:
        future_to_task = {}
        for i in range(args.num_tasks):
            logging.info(f"[Main] Submitting task {i}")
            future = executor.submit(process_task, i, args.server_ip, args.share_name, args.username, args.password, client_uuid)
            future_to_task[future] = i
        for future in concurrent.futures.as_completed(future_to_task):
            try:
                stats = future.result()
                if stats:
                    task_stats_list.append(stats)
            except Exception as e:
                task_id = future_to_task[future]
                logging.error(f"[Main] Task {task_id} failed with exception: {e}")
                if logging.getLogger().isEnabledFor(logging.DEBUG):
                    traceback.print_exc()
    elapsed_time = time.time() - start_time
    logging.info(f"Executed {len(task_stats_list)} tasks out of {args.num_tasks}")
    print_summary(task_stats_list, elapsed_time)

if __name__ == "__main__":
    main()
