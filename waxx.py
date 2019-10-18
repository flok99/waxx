#! /usr/bin/python3

import mysql.connector
import queue
import random
import socket
import sys
import threading
import time
import traceback

import ataxx.pgn
import ataxx.uai

# how many ms per move
tpm = 5000
# output
pgn_file = 'games.pgn'
# opening book, a list of FENs
book = 'openings.txt'
# gauntlet?
gauntlet = True

# this user needs a GRANT ALL
db_host = '192.168.64.1'
db_user = 'user'
db_pass = 'pass'
db_db = 'waxx'

###

try:
    conn = mysql.connector.connect(host=db_host, user=db_user, passwd=db_pass, database=db_db)
    c = conn.cursor()
    c.execute('CREATE TABLE results(ts datetime, p1 varchar(64), e1 varchar(128), t1 double, p2 varchar(64), e2 varchar(128), t2 double, result varchar(7), adjudication varchar(128), plies int, tpm int)')
    c.execute('CREATE TABLE players(user varchar(64), password varchar(64), primary key(user))')
    conn.commit()
    conn.close()
except Exception as e:
    print(e)
    pass

temp = open(book, 'r').readlines()
book_lines = [line.rstrip('\n') for line in temp]

lock = threading.Lock()

def play_game(p1_in, p2_in, t):
    global book_lines

    p1 = p1_in[0]
    p1_user = p1_in[1]
    p2 = p2_in[0]
    p2_user = p2_in[1]

    print('Starting game between %s(%s) and %s(%s)' % (p1.name, p1_user, p2.name, p2_user))

    pos = random.choice(book_lines)

    board = ataxx.Board(pos)

    reason = None

    fail2 = fail1 = False

    t1 = t2 = 0

    n_ply = 0

    while not board.gameover():
        start = time.time()

        if board.turn == ataxx.BLACK:
            p1.position(board.get_fen())
            bestmove, ponder = p1.go(movetime=t)

            if bestmove == None:
                fail1 = True
                reason = '%s disconnected' % p1.name
                p1.quit()

            t1 += time.time() - start

        else:
            p2.position(board.get_fen())
            bestmove, ponder = p2.go(movetime=t)

            if bestmove == None:
                fail2 = True
                reason = '%s disconnected' % p2.name
                p2.quit()

            t2 += time.time() - start

        if bestmove == None:
            if reason == None:
                reason = 'One/two clients disconnected'
            break

        n_ply += 1

        move = ataxx.Move.from_san(bestmove)

        if board.is_legal(move) == False:
            who = p1.name if board.turn == ataxx.BLACK else p2.name
            reason = 'Illegal move by %s: %s' % (who, bestmove)
            break

        board.makemove(move)

        if board.gameover():
            break
        
        if board.fifty_move_draw():
            reason = 'fifty moves'
            break

        if board.max_length_draw():
            reason = 'max length'
            break

    game = ataxx.pgn.Game()
    game.from_board(board)
    game.set_white(p1_user)
    game.set_black(p2_user)
    if reason:
        game.set_adjudicated(reason)

    print('%s(%s) versus %s(%s): %s (%s)' % (p1.name, p1_user, p2.name, p2_user, board.result(), reason))

    with lock:
        try:
            playing_clients.remove((p1_in, p2_in))

            if not fail1:
                idle_clients.append(p1_in)

            if not fail2:
                idle_clients.append(p2_in)

            fh = open(pgn_file, 'a')
            fh.write(str(game))
            fh.write('\n\n')
            fh.close()

            adjudication = reason if reason != None else ''

            conn = mysql.connector.connect(host=db_host, user=db_user, passwd=db_pass, database=db_db)
            c = conn.cursor()
            c.execute("INSERT INTO results(ts, p1, e1, t1, p2, e2, t2, result, adjudication, plies, tpm) VALUES(NOW(), %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)", (p1_user, p1.name, t1, p2_user, p2.name, t2, board.result(), adjudication, n_ply, t,))
            conn.commit()
            conn.close()

            if fail1:
                del p1_in

            if fail2:
                del p2_in

        except Exception as e:
            print('failure: %s' % e)

    return board.result()

def match_scheduler():
    while True:
        with lock:
            while True:
                n_idle = len(idle_clients)
                n_play = len(playing_clients)

                print('idle: %d, playing: %d' % (n_idle, n_play * 2))

                if n_idle < 2:
                    break

                i1 = i2 = 0

                while i1 == i2:
                    i1 = random.choice(idle_clients)
                    i2 = random.choice(idle_clients)

                idle_clients.remove(i1)
                idle_clients.remove(i2)

                playing_clients.append((i1, i2))

                t = threading.Thread(target=play_game, args=(i1, i2, tpm,))
                t.start()

        time.sleep(1.5)

def add_client(sck, addr):
    try:
        buf = ''
        while not '\n' in buf or not 'user ' in buf:
            buf += sck.recv(1024).decode()

        lf = buf.find('\n')
        user = buf[5:lf].lower().rstrip()

        if user == '':
            sck.close()
            return

        buf = buf[lf + 1:]
        while not '\n' in buf or not 'pass ' in buf:
            buf += sck.recv(1024).decode()

        lf = buf.find('\n')
        password = buf[5:lf].rstrip()

        if password == '':
            sck.close()
            return

        conn = mysql.connector.connect(host=db_host, user=db_user, passwd=db_pass, database=db_db)
        c = conn.cursor()
        c.execute('SELECT password FROM players WHERE user=%s', (user,))
        row = c.fetchone()
        conn.close()

        if row == None:
            conn = mysql.connector.connect(host=db_host, user=db_user, passwd=db_pass, database=db_db)
            c = conn.cursor()
            c.execute('INSERT INTO players(user, password) VALUES(%s, %s)', (user, password,))
            conn.commit()
            conn.close()

        elif row[0] != password:
            sck.send(bytes('Invalid password\n', encoding='utf8'))
            sck.close()
            return

        e = ataxx.uai.Engine(sck, True)
        e.uai()
        e.isready()

        print('Connected with %s (%s) running %s' % (addr, user, e.name))

        with lock:
            idle_clients.append((e, user))

    except Exception as e:
        print('Fail: %s' % e)
        sck.close()
        traceback.print_exc(file=sys.stdout)

idle_clients = []
playing_clients = []

t = threading.Thread(target=match_scheduler)
t.start()

HOST = ''
PORT = 28028
ss = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
ss.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
ss.bind((HOST, PORT))
ss.listen(128)

while True:

    # wait for a new client on a socket
    cs, addr = ss.accept()
    print(cs, addr)

    t = threading.Thread(target=add_client, args=(cs,addr,))
    t.start()
