#!/bin/bash

dev=$1
shift

#( stty speed 9600 ; ./duo-cp.py "$@" ) 3<>"$dev" <&3 >&3 2>&1

( ./duo-cp.py "$@" <&3 >&3 ) 3<>"$dev" 2>&1

#( ./duo-cp.py "$@" 1<>"$dev" <&1 ) 2>&1