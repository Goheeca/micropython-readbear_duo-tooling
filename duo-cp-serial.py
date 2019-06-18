#!/usr/bin/env python3

import serial
import sys
import os
import os.path
import binascii
import json


class LogSerialWrapper(object):
    def __init__(self, serial):
        self.serial = serial

    def write(self, data):
        res = self.serial.write(data)
        print(f'<{hex(id(self.serial))}>.write({data}) = {res}')

    def read(self, len):
        data = self.serial.read(len)
        print(f'<{hex(id(self.serial))}>.read({len}) = {data}')
        return data

    def read_until(self, until):
        data = self.serial.read_until(until)
        print(f'<{hex(id(self.serial))}>.read_until({until}) = {data}')
        return data

    def readall(self):
        data = self.serial.readall()
        print(f'<{hex(id(self.serial))}>.read_until() = {data}')
        return data

    def __setattr__(self, name, value):
        if name == 'serial':
            super().__setattr__(name, value)    
        else:
            super().__getattribute__('serial').__setattr__(name, value)
        
    #def __getattribute__(self, name):
    #    if name not in ['write', 'read', 'read_until', 'readall']:
    #        return super().__getattribute__('serial').__getattribute__(name)
    #    else:
    #        super().__getattribute__(name)
        

class DuoRepl(object):
    INTERRUPT = '\x03'
    EOL = '\r\n'  # b'\r\n'
    EOT = '\x04'
    RAW_MODE = '\x01'
    NORMAL_MODE = '\x02'
    CLEAR_TIMEOUT = 0.01

    def __init__(self, ser, timeout=CLEAR_TIMEOUT):
        self.ser = ser
        self.timeout = timeout
        self.ser.timeout = timeout

    def write(self, str_):
        self.ser.write(str_.encode())

    def read_until(self, until=EOL):
        return self.ser.read_until(until.encode()).decode()

    def readall(self):
        return self.ser.readall().decode()

    def write_end(self, str_, end=EOL):
        self.write(str_ + end)

    def raw_write_end(self, bin_):
        self.write_end(bin_, end=DuoRepl.EOT)

    def raw_result(self):
        stdout, stderr = self.readall()[2:-2].split(DuoRepl.EOT)
        return (stdout, stderr)

    def send(self, str_):
        self.write_end(str_, '\r')
        self.read_until(DuoRepl.EOL)

    def mode(self, raw=True):
        self.write(DuoRepl.INTERRUPT)
        self.write(DuoRepl.RAW_MODE if raw else DuoRepl.NORMAL_MODE)
        self.read_until()

    def clear(self):
        self.ser.timeout = DuoRepl.CLEAR_TIMEOUT
        self.readall()
        self.ser.timeout = self.timeout

    def readlines(self, n=None, eol=EOL):
        if n is None:
            return self.readall().split(eol)
        else:
            return [self.read_until(eol) for _ in range(n)]


class Sync(DuoRepl):
    def __init__(self, ser, timeout):
        super().__init__(ser, timeout)

    def __enter__(self):
        self.mode(raw=True)
        self.raw_write_end('import _utils')
        self.clear()
        self.raw_write_end('_utils.sync()')
        self.ser.read(2)
        return self

    def __exit__(self, exception_type, exception_value, traceback):
        self.clear()
        self.raw_write_end('')
        self.mode(raw=False)

    def result(self, str_):
        return str_.strip('\x00\r\n\t ')[:2] == 'OK'

    def do(self, str_, data=None, end=DuoRepl.EOT):
        self.send(str_)
        if data:
            self.write_end(data, end=end)
        content = self.read_until(until='\x00')[:-(1+len(end) if data else 1)]
        if content == '':
            content = None
        res = self.result(self.read_until())
        return (content, res)
        
    def perform(self, command, arg=None, data=None):
        action = command + (' ' + arg if arg else '')
        result = self.do(action, data=data)
        if not result[1]:
            raise RuntimeError(action)
        return result[0]

def checksum(path=None, content=None):
    if content is not None:
        return binascii.crc32(content.encode())
    if os.path.isfile(path):
        with open(path, 'r') as f:
            content = f.read()
            return binascii.crc32(content.encode())
    else:
        return None
    

def remove(path):
    if os.path.isfile(path):
        os.remove(path)
    else:
        for file in os.listdir(path):
            remove(os.path.join(path, file))
        os.rmdir(path)


def create(path, dir=True):
    if dir:
        if not os.path.isdir(path):
            try:
                remove(path)
            except:
                pass
        try:
            os.mkdir(path)
        except FileExistsError:
            pass
    else:
        if not os.path.isfile(path):
            try:
                remove(path)
            except:
                pass
        with open(path, 'a'):
            pass

def exists(path):
    return os.path.isfile(path) or os.path.isdir(path)
    
def deduplicate(listing):
    return set(filter(lambda file: file+'/' not in listing, listing))

class Remote(object):
    UPLOAD_BLOCK = 128

    def __init__(self, sync):
        self.sync = sync
        self._stat()
        
    def path_join(self, a, b):
        return os.path.join(a, b).replace('\\', '/')        
        
    def _stat(self):
        self.stat = json.loads(self.sync.perform('INFO', '/'))       

    def is_file(self, path):
        try:
            return isinstance(json.loads(self.sync.perform('INFO', path)), list)
        except RuntimeError:
            return False

    def is_dir(self, path):
        try:
            return isinstance(json.loads(self.sync.perform('INFO', path)), dict)
        except RuntimeError:
            return False 

    def create(self, path, dir=True):
        if dir:
            if not self.is_dir(path):
                try:
                    self.remove(path)
                except:
                    pass
            self.sync.perform('CREATE', self.path_join(path, ''))
        else:
            if not self.is_file(path):
                try:
                    self.remove(path)
                except:
                    pass
            self.sync.perform('CREATE', path)

    def listdir(self, path):
        return list({file for file, _ in json.loads(self.sync.perform('INFO', path)).items()}) 

    def checksum(self, path):
        try:
            return json.loads(self.sync.perform('INFO', path))[1]
        except RuntimeError:
            return None
            
    def exists(self, path):
        return self.is_file(path) or self.is_dir(path)
            
    def remove(self, path):
        if self.is_dir(path):
            for file in self.listdir(path):
                self.remove(self.path_join(path, file))
        self.sync.perform('REMOVE', path)            
        self._stat()

    def upload_file(self, path, content, binary=False):
        print(f'... -> REMOTE:{path}')
        if binary:
            content = binascii.b2a_base64(content.encode()).decode()
        prefix = 'BIN' if binary else ''
        if Remote.UPLOAD_BLOCK:
            first = True
            for block in (content[i:i+Remote.UPLOAD_BLOCK] for i in range(0, len(content), Remote.UPLOAD_BLOCK)):
                self.sync.perform(prefix + ('EDIT' if first else 'APPEND'), path, data=block)
                first = False
        else:
            self.sync.perform(prefix + 'EDIT', path, data=content)

    def download_file(self, path, binary=False):
        print(f'REMOTE:{path} -> ...')
        content = self.sync.perform('BINSHOW' if binary else 'SHOW', path)
        if binary:
            content = binascii.a2b_base64(content.encode()).decode()
        return content


    def upload(self, src_path, dst_path, binary=True, only_diffs=False):
        src_exists = exists(src_path)
        dst_exists = self.exists(dst_path)
        print(f'{src_path}[{src_exists}] -> REMOTE:{dst_path}[{dst_exists}]')
        same_type = src_exists != dst_exists or (os.path.isdir(src_path) if src_exists else None) == (self.is_dir(dst_path) if dst_exists else None)
        if not src_exists or not same_type:
            self.remove(dst_path)
        if not dst_exists or not same_type:
            self.create(dst_path, dir=os.path.isdir(src_path))
        if not src_exists:
            return

        if os.path.isdir(src_path):
            files = set(os.listdir(src_path))
            remote_files = set(self.listdir(dst_path))
            for file in deduplicate(set.union(files, remote_files)):
                self.upload(os.path.join(src_path, file), self.path_join(dst_path, file), binary, only_diffs)
        elif os.path.isfile(src_path):
            with open(src_path, 'r') as f:
                content = f.read()
                if not only_diffs or checksum(content=content) != self.checksum(dst_path):
                    self.upload_file(dst_path, content, binary)
        else:
            raise RuntimeError(src_path + ' -> REMOTE:' + dst_path)

    def download(self, src_path, dst_path, binary=True, only_diffs=False):
        src_exists = self.exists(src_path)
        dst_exists = exists(dst_path)  
        print(f'REMOTE:{src_path}[{src_exists}] -> {dst_path}[{dst_exists}]')
        same_type = src_exists != dst_exists or (self.is_dir(src_path) if src_exists else None) == (os.path.isdir(dst_path) if dst_exists else None)
        if not src_exists or not same_type:
            remove(dst_path)
        if not dst_exists or not same_type:
            create(dst_path, dir=self.is_dir(src_path))
        if not src_exists:
            return
        
        if self.is_dir(src_path):
            remote_files = set(self.listdir(src_path))
            files = set(os.listdir(dst_path))
            for file in deduplicate(set.union(files, remote_files)):
                self.download(self.path_join(src_path, file), os.path.join(dst_path, file), binary, only_diffs)
        elif self.is_file(src_path):
            if not only_diffs or checksum(dst_path) != self.checksum(src_path):
                content = self.download_file(src_path, binary)
                with open(dst_path, 'w') as f:
                    f.write(content)
        else:
            raise RuntimeError('REMOTE:' + src_path + ' -> ' + dst_path)

def main(argv):
    BAUD = 9600
    TIMEOUT = 1
    if len(argv) < 1:
        print('Required argument: a serial port to open.')
        sys.exit('')
    #if len(argv) >= 2:
    #    TIMEOUT = float(argv[1])
    if len(argv) < 4 and (not argv[1].startswith('u') or not argv[1].startswith('d')):
        print('Required arguments: (upload | download) source destination')
        sys.exit('')
        
    with serial.Serial(argv[0], BAUD) as ser:
        #with Sync(LogSerialWrapper(ser), TIMEOUT) as sync:
        with Sync(ser, TIMEOUT) as sync:
            remote = Remote(sync)            
            print('REMOTE:'+str(remote.stat))
            if argv[1][0] == 'u':
                remote.upload(argv[2], argv[3], only_diffs=True)
            else:
                remote.download(argv[2], argv[3], only_diffs=True)



if __name__ == '__main__':
    main(sys.argv[1:])
