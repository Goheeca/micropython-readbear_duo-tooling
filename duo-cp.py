#!/usr/bin/env python3

import sys
import select

def log(str):
    print(str, file=sys.stderr)
    
def read_rest():
    while sys.stdin in select.select([sys.stdin], [], [], 0)[0]:
        line = sys.stdin.readline()
        log('READ: ' + line)
    else:
        log('NOTHING TO BE READ')

log('Here we go')

print('toggle_led()')
log('READ: ' + sys.stdin.readline())
log('READ: ' + sys.stdin.readline())
log('Toggled')