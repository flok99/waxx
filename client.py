#! /usr/bin/python3

import fcntl
import getopt
import os
import select
import socket
import subprocess
import sys
import time
import traceback

def usage():
    print('-e x  program to invoke (Ataxx "engine")')
    print('-i x  server to connect to')
    print('-p x  port to connect to (usually 28028)')
    print('-U x  username to use')
    print('-P x  password to use')

engine = None
host = 'server.ataxx.org'
port = 28028
user = None
password = None

try:
    optlist, args = getopt.getopt(sys.argv[1:], 'e:i:p:U:P:')

    for o, a in optlist:
        if o == '-e':
            engine = a
        elif o == '-i':
            host = a
        elif o == '-p':
            port = int(a)
        elif o == '-U':
            user = a
        elif o == '-P':
            password = a
        else:
            print(o, a)

except getopt.GetoptError as err:
    print(err)
    usage()
    sys.exit(1)

if user == None or password == None:
    print('No user or password given')
    usage()
    sys.exit(1)

while True:
    try:
        p = subprocess.Popen(engine, stdin=subprocess.PIPE, stdout=subprocess.PIPE, universal_newlines=True)
        fl = fcntl.fcntl(p.stdout, fcntl.F_GETFL)
        fcntl.fcntl(p.stdout, fcntl.F_SETFL, fl | os.O_NONBLOCK)

        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect((host, port))

        s.send(bytes('user %s\n' % user, encoding='utf8'))
        s.send(bytes('pass %s\n' % password, encoding='utf8'))

        poller = select.poll()
        poller.register(s.fileno(), select.POLLIN)
        poller.register(p.stdout.fileno(), select.POLLIN)

        terminate = False

        while not terminate:
            events = poller.poll(-1)
            if events == None:
                print('Poller returned error?')
                break

            for fd, flag in events:
                if fd == s.fileno():
                    dat = s.recv(4096)
                    if dat == None:
                        terminate = True
                    else:
                        print(time.asctime(), 'server: %s' % dat.decode())
                        if p.stdin.write(dat.decode()) == 0:
                            terminate = True
                        p.stdin.flush()

                elif fd == p.stdout.fileno():
                    dat = p.stdout.read()
                    if dat == None:
                        terminate = True
                    else:
                        print(time.asctime(), 'engine: ', dat)
                        if s.send(dat.encode('utf-8')) == 0:
                            terminate = True

                else:
                    print('Unexpected error ', fd, flag)
                    break

        if terminate:
            time.sleep(2.5)

    except ConnectionRefusedError as e:
        print('failure: %s' % e)
        time.sleep(2.5)

    except Exception as e:
        print('failure: %s' % e)
        traceback.print_exc(file=sys.stdout)
        break

    finally:
        s.close()
        del s

        p.stdout.close()
        p.terminate()
        p.wait()
        del p
