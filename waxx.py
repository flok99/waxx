#! /usr/bin/python3

import queue
import random
import socket
import sqlite3
import threading
import time

import ataxx.pgn
import ataxx.uai

# how many ms per move
tpm = 150
# output
pgn_file = 'games.pgn'
# opening book, a list of FENs
book = 'openings.txt'
# gauntlet?
gauntlet = True
# how many games to play concurrently
max_concurrent = 32

db_file = 'games.db'

###

try:
    conn = sqlite3.connect(db_file)
    c = conn.cursor()
    c.execute('PRAGMA journal_mode=WAL')
    c.execute('CREATE TABLE results(ts datetime, p1 varchar(64), p2 varchar(64), result varchar(7))')
    c.execute('CREATE TABLE players(user varchar(64), password varchar(64))')
    conn.commit()
    conn.close()
except:
    pass

temp = open(book, 'r').readlines()
book_lines = [line.rstrip('\n') for line in temp]

lock = threading.Lock()

def play_game(p1, p2, t):
    global book_lines

    print('Starting game between %s and %s' % (p1.name, p2.name))

    pos = random.choice(book_lines)

    board = ataxx.Board(pos)

    reason = None

    fail2 = fail1 = False

    while not board.gameover():
        if board.turn == ataxx.BLACK:
            p1.position(board.get_fen())
            bestmove, ponder = p1.go(movetime=t)

            if bestmove == None:
                fail1 = True
                p1.quit()

        else:
            p2.position(board.get_fen())
            bestmove, ponder = p2.go(movetime=t)

            if bestmove == None:
                fail2 = True
                p2.quit()

        if bestmove == None:
            reason = 'One/two clients disconnected'
            break

        move = ataxx.Move.from_san(bestmove)

        if board.is_legal(move) == False:
            reason = 'Illegal move: %s' % bestmove
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
    game.set_white(p1.name)
    game.set_black(p2.name)
    if reason:
        game.set_adjudicated(reason)

    print('%s versus %s: %s' % (p1.name, p2.name, board.result()))

    with lock:
        try:
            playing_clients.remove((p1, p2))

            if not fail1:
                idle_clients.append(p1)

            if not fail2:
                idle_clients.append(p2)

            fh = open(pgn_file, 'a')
            fh.write(str(game))
            fh.write('\n\n')
            fh.close()

            conn = sqlite3.connect(db_file)
            c = conn.cursor()
            c.execute('INSERT INTO results(p1, p2, result) VALUES(?, ?, ?)', (p1.name, p2.name, board.result(),))
            conn.commit()
            conn.close()

            if fail1:
                del p1

            if fail2:
                del p2

        except Exception as e:
            print('failure: %s' % e)

    return board.result()

def match_scheduler():
    while True:
        with lock:
            n_idle = len(idle_clients)
            n_play = len(playing_clients)

            print('idle: %d, playing: %d' % (n_idle, n_play * 2))

            if n_idle >= 2 and n_play < max_concurrent:

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

        conn = sqlite3.connect(db_file)
        c = conn.cursor()
        c.execute('SELECT password FROM players WHERE user=?', (user,))
        row = c.fetchone()
        conn.close()

        if row == None:
            conn = sqlite3.connect(db_file)
            c = conn.cursor()
            c.execute('INSERT INTO players(user, password) VALUES(?, ?)', (user, password,))
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
            idle_clients.append(e)

    except Exception as e:
        print('Fail: %s' % e)
        sck.close()

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
