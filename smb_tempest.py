#!/usr/bin/env python3
"""
Name:   smb_tempest.py
Author: KMac and Sheila
Date:   May 18th, 2025

Unleash the storm on your SMB server.

Description:
------------
smb_tempest.py is a multi-threaded SMB session generator and load tester.
It connects to an SMB share, creates client-specific directories,
writes large files, performs sequential reads, spawns and deletes
many small random files, and measures performance throughout.

Supported Modes:
----------------
--mode_streaming_reads
  • Reads an existing file from start to finish using large block sizes (default 1MB).
  • Simulates streaming, backups, or ML dataset reading.
  • File must already exist.

--mode_read_iops
  • Performs many tiny reads (4KB each) from the beginning of an existing file.
  • Simulates high-I/O workloads like databases or metadata scanning.
  • File must already exist. Default is 1024 reads.

--mode_streaming_writes
  • Writes a brand new file using large blocks (default 1MB) until a size limit is reached.
  • Simulates high-throughput sequential writes.

--mode_random_io
  • Performs a mix of random reads and writes on an existing file.
  • Simulates unpredictable I/O like virtual machines or shared user access.
  • File must already exist. Requires --max_random_io_readpct to control read ratio.

You may also pass configuration using a JSON file with --config_file.
If not specified, smb_tempest_cfg.json is used by default if found,
with a prompt for confirmation before loading.
"""

import argparse
import concurrent.futures
import logging
import os
import random
import time
import uuid
import traceback
import json
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

DEFAULT_CONFIG_FILE = "smb_tempest_cfg.json"

def retry_operation(max_attempts=3, delay_seconds=1):
    def decorator(func):
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

def human_readable_bytes(num_bytes):
    if num_bytes >= 1024**3:
        return f"{num_bytes / 1024**3:.2f} GB"
    elif num_bytes >= 1024**2:
        return f"{num_bytes / 1024**2:.2f} MB"
    elif num_bytes >= 1024:
        return f"{num_bytes / 1024:.2f} KB"
    else:
        return f"{num_bytes} B"

def infer_mode_label(args):
    if args.mode_streaming_reads:
        return "streaming_reads"
    if args.mode_read_iops:
        return "read_iops"
    if args.mode_streaming_writes:
        return "streaming_writes"
    if args.mode_random_io:
        return "random_io"
    return "default (write stream → read stream → churn small random files)"

def print_config_summary(args, client_uuid):
    readable_block = human_readable_bytes(args.block_size)
    print(f"""
==================== SMB Tempest Configuration ====================
Target SMB Server     : {args.smb_server_address}
Share Name            : {args.share_name}
Username              : {args.username}
Block Size            : {readable_block}
Max File Size         : {args.max_file_size} MiB
Number of Sessions    : {args.num_smb_sessions}
Mode                  : {infer_mode_label(args)}
Client UUID Directory : {client_uuid}
====================================================================
""")

def load_config(config_path):
    with open(config_path, 'r') as f:
        data = json.load(f)
    return argparse.Namespace(**data)

def merge_args_with_config(args):
    config_path = args.config_file or DEFAULT_CONFIG_FILE
    if os.path.exists(config_path):
        if not args.config_file:
            confirm = input(f"Default config file '{config_path}' found. Load it? (y/N): ").strip().lower()
            if confirm in ("n", "no"):
                return args
        config_args = load_config(config_path)
        for key, value in vars(config_args).items():
            cli_value = getattr(args, key, None)
            if isinstance(cli_value, bool):
                if cli_value is False:
                    setattr(args, key, value)
            elif cli_value == parser.get_default(key):
                setattr(args, key, value)

        for int_field in ["num_smb_sessions", "max_file_size", "block_size", "num_iops_reads", "num_random_ops", "max_random_io_readpct"]:
            try:
                val = getattr(args, int_field, None)
                if isinstance(val, str):
                    setattr(args, int_field, int(val))
            except Exception:
                pass
    return args

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

def process_task(task_id, args, client_uuid):
    server_ip = args.smb_server_address
    share_name = args.share_name
    try:
        conn = Connection("smbclient", server_ip, port=445, require_signing=False)
        conn.client_guid = uuid.uuid4().bytes
        conn.connect()
        session = Session(conn, args.username, args.password)
        session.connect()
        tree = TreeConnect(session, f"\\\\{server_ip}\\{share_name}")
        tree.connect()

        client_dir = client_uuid
        ensure_directory_exists(tree, client_dir)
        remote_file_path = f"{client_dir}\\smb_tempest.{task_id}"
        stats = {"mode": infer_mode_label(args)}

        if args.mode_streaming_reads:
            args.block_size = 4 * 1024 * 1024
            stats["bytes_read"] = smb_read_file(session, server_ip, share_name, remote_file_path, args.block_size)
            stats["num_random_files"] = 0

        elif args.mode_read_iops:
            stats["bytes_read"] = smb_iops_read(session, server_ip, share_name, remote_file_path, args.num_iops_reads)
            stats["num_random_files"] = 0

        elif args.mode_streaming_writes:
            smb_create_file(tree, remote_file_path, args.max_file_size * 1024**2, args.block_size)
            stats["bytes_read"] = 0
            stats["num_random_files"] = 0

        elif args.mode_random_io:
            stats["bytes_read"] = smb_random_io(session, server_ip, share_name, remote_file_path,
                                                args.max_file_size * 1024**2,
                                                args.block_size,
                                                num_ops=args.num_random_ops,
                                                read_pct=args.max_random_io_readpct)
            stats["num_random_files"] = 0

        else:
            smb_create_file(tree, remote_file_path, args.max_file_size * 1024**2, args.block_size)
            stats["bytes_read"] = smb_read_file(session, server_ip, share_name, remote_file_path, args.block_size)
            random_files = []
            for seq in range(random.randint(10, 10000)):
                random_file = f"{client_dir}\\{seq}_randomfile.{task_id}"
                smb_create_random_file(tree, random_file)
                random_files.append(random_file)
            for random_file in random_files:
                smb_delete_file(session, server_ip, share_name, random_file)
            stats["num_random_files"] = len(random_files)

        tree.disconnect()
        session.disconnect()
        conn.disconnect()
        return stats

    except Exception as e:
        logging.error(f"[Task {task_id}] Exception: {e}")
        traceback.print_exc()
        return {}

@retry_operation(max_attempts=5, delay_seconds=2)
def smb_create_file(tree, remote_file_path, size, block_size):
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
    buffer = os.urandom(block_size)
    while total_written < size:
        to_write = min(block_size, size - total_written)
        file.write(buffer[:to_write], total_written)
        total_written += to_write
    file.flush()
    file.close()
    time.sleep(1)

@retry_operation(max_attempts=5, delay_seconds=2)
def smb_random_io(session, server_ip, share_name, remote_file_path, file_size, block_size, num_ops=100, read_pct=50):
    tree = TreeConnect(session, f"\\\\{server_ip}\\{share_name}")
    tree.connect()
    file = Open(tree, remote_file_path)
    file.create(
        impersonation_level=ImpersonationLevel.Impersonation,
        desired_access=FilePipePrinterAccessMask.GENERIC_READ | FilePipePrinterAccessMask.GENERIC_WRITE,
        file_attributes=FileAttributes.FILE_ATTRIBUTE_NORMAL,
        share_access=ShareAccess.FILE_SHARE_READ | ShareAccess.FILE_SHARE_WRITE,
        create_disposition=CreateDisposition.FILE_OPEN,
        create_options=CreateOptions.FILE_NON_DIRECTORY_FILE,
    )
    total_bytes = 0
    read_ratio = read_pct / 100.0
    for _ in range(num_ops):
        offset = random.randint(0, max(0, file_size - block_size))
        if random.random() < read_ratio:
            try:
                data = file.read(offset, block_size)
                total_bytes += len(data)
            except Exception:
                continue
        else:
            file.write(os.urandom(block_size), offset)
            total_bytes += block_size
    file.flush()
    file.close()
    tree.disconnect()
    return total_bytes

@retry_operation(max_attempts=5, delay_seconds=2)
def smb_read_file(session, server_ip, share_name, remote_file_path, block_size):
    MAX_SMB_READ_SIZE = 1024 * 1024  # 1 MiB max safety
    block_size = min(block_size, MAX_SMB_READ_SIZE)

    tree = TreeConnect(session, f"\\\\{server_ip}\\{share_name}")
    tree.connect()
    file = Open(tree, remote_file_path)
    file.create(
        impersonation_level=1,  # ImpersonationLevel.Impersonation
        desired_access=0x120089,  # GENERIC_READ
        file_attributes=0x80,  # NORMAL
        share_access=1,  # FILE_SHARE_READ
        create_disposition=1,  # FILE_OPEN
        create_options=0x40  # NON_DIRECTORY_FILE
    )

    file_size = file.end_of_file

    def read_chunk(offset):
        try:
            return len(file.read(offset, block_size))
        except Exception:
            return 0

    total_bytes = 0
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            offsets = range(0, file_size, block_size)
            futures = [executor.submit(read_chunk, offset) for offset in offsets]
            for future in concurrent.futures.as_completed(futures):
                total_bytes += future.result()
    finally:
        file.close()
        tree.disconnect()
    return total_bytes

def print_summary(task_stats_list, elapsed_time):
    total_tasks = len(task_stats_list)
    total_bytes = sum(stats.get("bytes_read", 0) for stats in task_stats_list)
    total_files = sum(stats.get("num_random_files", 0) for stats in task_stats_list)
    throughput = (total_bytes / 1024**2) / elapsed_time if elapsed_time > 0 else 0
    max_iops = int((total_bytes / 4096) / elapsed_time) if elapsed_time > 0 else 0
    max_throughput = throughput
    readable_total = human_readable_bytes(total_bytes)
    modes = set(stats.get("mode", "default") for stats in task_stats_list)

    print(f"""
================== Test Summary ==================
Test Mode(s) Used          : {', '.join(modes)}
Total Tasks Executed       : {total_tasks}
Total Random Files Created : {total_files}
Total Read/IO Volume       : {readable_total}
Total Time Taken           : {elapsed_time:.2f} seconds
Max Throughput Achieved    : {max_throughput:.2f} MB/s
Max IOPS Achieved          : {max_iops:,} IOPS
==================================================
""")
    if total_bytes == 0:
        print("Warning: Nothing read! Check network availability, permissions, environmentals...")
    print("SMB Tempest complete.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SMB Session Generator (Tempest Edition)",
                                     formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    mode_group = parser.add_mutually_exclusive_group()
    parser.add_argument("--smb_server_address")
    parser.add_argument("--share_name")
    parser.add_argument("--username")
    parser.add_argument("--password")
    parser.add_argument("--num_smb_sessions", type=int, default=1)
    parser.add_argument("--max_file_size", type=int, default=1024)
    parser.add_argument("--block_size", type=int, default=1024*1024)
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--fail_fast", action="store_true")
    parser.add_argument("--num_iops_reads", type=int, default=1024)
    parser.add_argument("--num_random_ops", type=int, default=100)
    parser.add_argument("--max_random_io_readpct", type=int, help="Required read percentage for mode_random_io")
    mode_group.add_argument("--mode_streaming_reads", action="store_true")
    mode_group.add_argument("--mode_read_iops", action="store_true")
    mode_group.add_argument("--mode_streaming_writes", action="store_true")
    mode_group.add_argument("--mode_random_io", action="store_true")
    parser.add_argument("--config_file")
    args = parser.parse_args()
    args = merge_args_with_config(args)

    if args.mode_random_io and args.max_random_io_readpct is None:
        parser.error("--max_random_io_readpct is required when --mode_random_io is used")

    setup_logging(debug=args.debug)
    client_uuid = get_client_uuid()
    print_config_summary(args, client_uuid)
    print("\nStarting test...\n")

    task_stats = []
    start = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.num_smb_sessions) as executor:
        futures = [executor.submit(process_task, i, args, client_uuid)
                   for i in range(args.num_smb_sessions)]
        for f in concurrent.futures.as_completed(futures):
            try:
                result = f.result()
                if result:
                    task_stats.append(result)
            except Exception as e:
                logging.error(f"Task failed: {e}")
                if args.fail_fast:
                    break
    elapsed = time.time() - start
    print_summary(task_stats, elapsed)