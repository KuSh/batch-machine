import logging; _L = logging.getLogger('openaddr.util')

from urllib.parse import urlparse, parse_qsl, urljoin
from datetime import datetime, timedelta, date
from os.path import join, basename, splitext, dirname, exists
from operator import attrgetter
from tempfile import mkstemp
from os import close, getpid
import glob
import collections
import ftplib
import httmock
import io
import zipfile
import time
import re

RESOURCE_LOG_INTERVAL = timedelta(seconds=30)
RESOURCE_LOG_FORMAT = 'Resource usage: {{ user: {user:.0f}%, system: {system:.0f}%, ' \
    'memory: {memory:.0f}MB, read: {read:.0f}KB, written: {written:.0f}KB, ' \
    'sent: {sent:.0f}KB, received: {received:.0f}KB, period: {period:.0f}sec, ' \
    'procs: {procs:.0f} }}'

def build_request_ftp_file_callback():
    '''
    '''
    file = io.BytesIO()
    callback = lambda bytes: file.write(bytes)
    return file, callback

def request_ftp_file(url):
    '''
    '''
    _L.info('Getting {} via FTP'.format(url))
    parsed = urlparse(url)

    try:
        ftp = ftplib.FTP(parsed.hostname)
        ftp.login(parsed.username, parsed.password)

        file, callback = build_request_ftp_file_callback()
        ftp.retrbinary('RETR {}'.format(parsed.path), callback)
        file.seek(0)
    except Exception as e:
        _L.warning('Got an error from {}: {}'.format(parsed.hostname, e))
        return httmock.response(400, b'', headers={'Content-Type': 'application/octet-stream'})

    # Using mock response because HTTP responses are expected downstream
    return httmock.response(200, file.read(), headers={'Content-Type': 'application/octet-stream'})

def get_pidlist(start_pid):
    ''' Return a set of recursively-found child PIDs of the given start PID.
    '''
    children = collections.defaultdict(set)

    for path in glob.glob('/proc/*/status'):
        _, _, pid, _ = path.split('/', 3)
        if pid in ('thread-self', 'self'):
            continue
        with open(path) as file:
            for line in file:
                if line.startswith('PPid:\t'):
                    ppid = line[6:].strip()
                    break
            children[int(ppid)].add(int(pid))

    parents, pids = [start_pid], set()

    while parents:
        parent = parents.pop(0)
        pids.add(parent)
        parents.extend(children[parent])

    return pids

def get_cpu_times(pidlist):
    ''' Return Linux CPU usage times in jiffies.

        See http://stackoverflow.com/questions/1420426/how-to-calculate-the-cpu-usage-of-a-process-by-pid-in-linux-from-c
    '''
    if not exists('/proc/stat') or not exists('/proc/self/stat'):
        return None, None, None

    with open('/proc/stat') as file:
        stat = re.split(r'\s+', next(file).strip())
        time_total = sum([int(s) for s in stat[1:]])

    utime, stime = 0, 0

    for pid in pidlist:
        with open('/proc/{}/stat'.format(pid)) as file:
            stat = next(file).strip().split(' ')
            utime += int(stat[13])
            stime += int(stat[14])

    return time_total, utime, stime

def get_diskio_bytes(pidlist):
    ''' Return bytes read and written.

        This will measure all bytes read in the process, and so includes
        reading in shared libraries, etc; not just our productive data
        processing activity.

        See http://stackoverflow.com/questions/3633286/understanding-the-counters-in-proc-pid-io
    '''
    if not exists('/proc/self/io'):
        return None, None

    read_bytes, write_bytes = 0, 0

    for pid in pidlist:
        with open('/proc/{}/io'.format(pid)) as file:
            for line in file:
                bytes = re.split(r':\s+', line.strip())
                if 'read_bytes' in bytes:
                    read_bytes += int(bytes[1])
                if 'write_bytes' in bytes:
                    write_bytes += int(bytes[1])

    return read_bytes, write_bytes

def get_network_bytes():
    ''' Return bytes sent and received.

        TODO: This code measures network usage for the whole system.
        It'll be better to do this measurement on a per-process basis later.
    '''
    if not exists('/proc/net/netstat'):
        return None, None

    sent_bytes, recv_bytes = None, None

    with open('/proc/net/netstat') as file:
        for line in file:
            columns = line.strip().split()
            if 'IpExt:' in line:
                values = next(file).strip().split()
                netstat = {k: int(v) for (k, v) in zip(columns[1:], values[1:])}
                sent_bytes, recv_bytes = netstat['OutOctets'], netstat['InOctets']

    return sent_bytes, recv_bytes

def get_memory_usage(pidlist):
    ''' Return Linux memory usage in megabytes.

        VMRSS is of interest here too; that's resident memory size.
        It will matter if a machine runs out of RAM.

        See http://stackoverflow.com/questions/30869297/difference-between-memfree-and-memavailable
        and http://stackoverflow.com/questions/131303/how-to-measure-actual-memory-usage-of-an-application-or-process
    '''
    if not exists('/proc/self/status'):
        return None

    megabytes = 0

    for pid in pidlist:
        with open('/proc/{}/status'.format(pid)) as file:
            for line in file:
                if 'VmSize' in line:
                    size = re.split(r'\s+', line.strip())
                    megabytes += int(size[1]) / 1024
                    break

    return megabytes

def log_current_usage(start_time, usercpu_prev, syscpu_prev, totcpu_prev, read_prev, written_prev, sent_prev, received_prev, time_prev):
    '''
    '''
    pidlist = get_pidlist(getpid())
    totcpu_curr, usercpu_curr, syscpu_curr = get_cpu_times(pidlist)
    read_curr, written_curr = get_diskio_bytes(pidlist)
    sent_curr, received_curr = get_network_bytes()
    time_curr = time.time()

    if totcpu_prev is not None:
        # Log resource usage by comparing to previous tick
        megabytes_used = get_memory_usage(pidlist)
        user_cpu = (usercpu_curr - usercpu_prev) / (totcpu_curr - totcpu_prev)
        sys_cpu = (syscpu_curr - syscpu_prev) / (totcpu_curr - totcpu_prev)
        if read_curr is None or read_prev is None or written_curr is None or written_prev is None:
            read = written = sent = received = 0
        else:
            read, written = read_curr - read_prev, written_curr - written_prev
            sent, received = sent_curr - sent_prev, received_curr - received_prev

        percent, K = .01, 1024
        _L.info(RESOURCE_LOG_FORMAT.format(
            user=user_cpu/percent, system=sys_cpu/percent, memory=megabytes_used,
            read=read/K, written=written/K, sent=sent/K, received=received/K,
            procs=len(pidlist), period=time_curr - time_prev
            ))

    return usercpu_curr, syscpu_curr, totcpu_curr, read_curr, written_curr, sent_curr, received_curr, time_curr

def log_process_usage(lock):
    '''
    '''
    start_time = time.time()
    next_measure = start_time
    previous = (None, None, None, None, None, None, None, None)

    while True:
        time.sleep(.05)

        if lock.acquire(False):
            # Got the lock, we are done. Log one last time and get out.
            log_current_usage(start_time, *previous)
            return

        if time.time() <= next_measure:
            # Not yet time to measure and log usage.
            continue

        previous = log_current_usage(start_time, *previous)
        next_measure += RESOURCE_LOG_INTERVAL.seconds + RESOURCE_LOG_INTERVAL.days * 86400
