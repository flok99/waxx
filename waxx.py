#! /usr/bin/python3

import hashlib
import json
import mysql.connector
import queue
import random
from random import randint
import socket
import sys
import threading
import time
import traceback

from http.server import ThreadingHTTPServer, HTTPServer, BaseHTTPRequestHandler

from EloPy import elopy

import ataxx.pgn
import ataxx.uai

# how many ms per move
tpm = 5000
time_buffer_soft = 200 # be aware of ping times
time_buffer_hard = 1000
# output
pgn_file = None
# opening book, a list of FENs
book = 'openings.txt'
# gauntlet?
gauntlet = True

# this user needs a GRANT ALL
db_host = '192.168.64.1'
db_user = 'user'
db_pass = 'pass'
db_db = 'waxx'

# http server
http_port = 7623

# match history
match_history_size = 25

logfile = 'waxx.log'

###

def flog(what):
    if not logfile:
        return

    try:
        ts = time.asctime()

        print(ts, what)

        fh = open(logfile, 'a')
        fh.write('%s %s\n' % (ts, what))
        fh.close()

    except Exception as e:
        print('Logfile failure %s' % e)

try:
    conn = mysql.connector.connect(host=db_host, user=db_user, passwd=db_pass, database=db_db)
    c = conn.cursor()
    c.execute('CREATE TABLE results(ts datetime, p1 varchar(64), e1 varchar(128), t1 double, p2 varchar(64), e2 varchar(128), t2 double, result varchar(7), adjudication varchar(128), plies int, tpm int, pgn text, md5 char(32))')
    c.execute('CREATE TABLE players(user varchar(64), password varchar(64), rating double default 1000, w int(8) default 0, d int(8) default 0, l int(8) default 0, failure_count int(8) default 0, primary key(user))')
    conn.commit()
    conn.close()
except Exception as e:
    flog('db create: %s' % e)
    pass

temp = open(book, 'r').readlines()
book_lines = [line.rstrip('\n') for line in temp]

lock = threading.Lock()
last_activity = {}

def play_game(p1_in, p2_in, t, time_buffer_soft, time_buffer_hard):
    global book_lines

    fail2 = fail1 = False

    try:
        p1 = p1_in[0]
        p1_user = p1_in[1]
        p2 = p2_in[0]
        p2_user = p2_in[1]

        flog('Starting game between %s(%s) and %s(%s)' % (p1.name, p1_user, p2.name, p2_user))

        p1.uainewgame()
        p1.setoption('UCI_Opponent', 'none none computer %s' % p2.name)
        p2.uainewgame()
        p2.setoption('UCI_Opponent', 'none none computer %s' % p1.name)

        pos = random.choice(book_lines)

        board = ataxx.Board(pos)

        reason = None

        t1 = t2 = 0

        n_ply = 0

        while not board.gameover():
            start = time.time()
            took = None

            who = p1.name if board.turn == ataxx.BLACK else p2.name

            maxwait = (t + time_buffer_hard) / 1000.0

            if board.turn == ataxx.BLACK:
                p1.position(board.get_fen())
                bestmove, ponder = p1.go(movetime=t, maxwait=maxwait)

                if bestmove == None:
                    fail1 = True
                    reason = '%s disconnected' % p1.name
                    p1.quit()

                now = time.time()
                took = now - start
                t1 += took

                with lock:
                    last_activity[p1.name] = now

            else:
                p2.position(board.get_fen())
                bestmove, ponder = p2.go(movetime=t, maxwait=maxwait)

                if bestmove == None:
                    fail2 = True
                    reason = '%s disconnected' % p2.name
                    p2.quit()

                now = time.time()
                took = now - start
                t2 += took

                with lock:
                    last_activity[p2.name] = now

            t_left = t + time_buffer_soft - took * 1000
            if t_left < 0 and reason == None:
                reason = '%s used too much time' % who
                flog('%s used %fms too much time' % (who, -t_left))

                if t + time_buffer_hard - took * 1000 < 0:
                    flog('%s went over the hard limit' % who)
                    break

            if bestmove == None:
                if reason == None:
                    reason = 'One/two clients disconnected'
                break

            n_ply += 1

            flog('%s) %s => %s' % (who, board.get_fen(), bestmove))
            move = ataxx.Move.from_san(bestmove)

            if board.is_legal(move) == False:
                who = p1.name if board.turn == ataxx.BLACK else p2.name
                reason = 'Illegal move by %s: %s' % (who, bestmove)

                if board.turn == ataxx.BLACK:
                    fail1 = True
                else:
                    fail2 = True
                break

            board.makemove(move)

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

        flog('%s(%s) versus %s(%s): %s (%s)' % (p1.name, p1_user, p2.name, p2_user, board.result(), reason))

        with lock:
            # update internal structures representing who is playing or not
            playing_clients.remove((p1_in, p2_in))

            conn = mysql.connector.connect(host=db_host, user=db_user, passwd=db_pass, database=db_db)
            c = conn.cursor()

            if fail1:
                c.execute("UPDATE players SET failure_count=failure_count+1 WHERE user=%s", (p1_user,))
            else:
                idle_clients.append(p1_in)

            if fail2:
                c.execute("UPDATE players SET failure_count=failure_count+1 WHERE user=%s", (p2_user,))
            else:
                idle_clients.append(p2_in)

            conn.commit()
            conn.close()

            # update pgn file
            if pgn_file:
                fh = open(pgn_file, 'a')
                fh.write(str(game))
                fh.write('\n\n')
                fh.close()

            # put result record in results table
            pgn = str(game)
            hash_in = '%f %s %s' % (time.time(), p1.name, p2.name)
            hash_ = hashlib.md5(hash_in.encode('utf-8')).hexdigest()

            adjudication = reason if reason != None else ''

            conn = mysql.connector.connect(host=db_host, user=db_user, passwd=db_pass, database=db_db)
            c = conn.cursor()
            c.execute("INSERT INTO results(ts, p1, e1, t1, p2, e2, t2, result, adjudication, plies, tpm, pgn, md5) VALUES(NOW(), %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)", (p1_user, p1.name, t1, p2_user, p2.name, t2, board.result(), adjudication, n_ply, t, pgn, hash_))
            conn.commit()
            conn.close()

            # update rating of the user
            if not fail1 and not fail2:
                i = elopy.Implementation()

                conn = mysql.connector.connect(host=db_host, user=db_user, passwd=db_pass, database=db_db)
                c = conn.cursor()

                # get
                c.execute("SELECT rating FROM players WHERE user=%s", (p1_user,))
                row = c.fetchone()
                i.addPlayer(p1_user, rating=float(row[0]))

                c.execute("SELECT rating FROM players WHERE user=%s", (p2_user,))
                row = c.fetchone()
                i.addPlayer(p2_user, rating=float(row[0]))

                # update
                if board.result() == '1-0':
                    i.recordMatch(p1_user, p2_user, winner=p1_user)
                elif board.result() == '0-1':
                    i.recordMatch(p1_user, p2_user, winner=p2_user)
                else:
                    i.recordMatch(p1_user, p2_user, draw=True)

                # put
                for r in i.getRatingList():
                    c.execute("UPDATE players SET rating=%s WHERE user=%s", (r[1], r[0]))

                if board.result() == '1-0':
                    c.execute("UPDATE players SET w=w+1 WHERE user=%s", (p1_user,))
                    c.execute("UPDATE players SET l=l+1 WHERE user=%s", (p2_user,))
                elif board.result() == '0-1':
                    c.execute("UPDATE players SET l=l+1 WHERE user=%s", (p1_user,))
                    c.execute("UPDATE players SET w=w+1 WHERE user=%s", (p2_user,))
                else:
                    c.execute("UPDATE players SET d=d+1 WHERE user=%s", (p1_user,))
                    c.execute("UPDATE players SET d=d+1 WHERE user=%s", (p2_user,))

                conn.commit()
                conn.close()

                del i

    except Exception as e:
        flog('failure: %s' % e)
        fh = open(logfile, 'a')
        traceback.print_exc(file=fh)
        fh.close()

        fail1 = fail2 = True

    if fail1:
        p1_in.quit()
        del p1_in

    if fail2:
        p2_in.quit()
        del p2_in

# https://stackoverflow.com/questions/14992521/python-weighted-random
def weighted_random(pairs):
    total = sum(pair[0] for pair in pairs)

    r = randint(1, total)

    for(weight, value) in pairs:
        r -= weight

        if r <= 0:
            return value

def select_client(idle_clients):
    pairs = []

    conn = mysql.connector.connect(host=db_host, user=db_user, passwd=db_pass, database=db_db)
    c = conn.cursor()

    c.execute('SELECT MAX(w + d + l) AS count FROM players')
    max_ = c.fetchone()[0]

    for client in idle_clients:
        c.execute('SELECT w + d + l AS count FROM players WHERE user=%s', (client[1],))
        row = c.fetchone()

        pairs.append((round(max_ - row[0]), client))

    conn.close()

    return weighted_random(pairs)

def match_scheduler():
    before = []

    while True:
        with lock:
            n_idle = len(idle_clients)
            n_play = len(playing_clients)

            flog('idle: %d, playing: %d' % (n_idle, n_play * 2))

            for loop in range(0, n_idle // 2):
                i1 = i2 = 0

                attempt = 0
                while i1 == i2:
                    i1 = select_client(idle_clients)
                    i2 = random.choice(idle_clients)

                    attempt += 1
                    if attempt >= 5:
                        break

                if i1 == i2:
                    flog('Cannot find a pair')
                    break

                pair = '%s | %s' % (i1[1], i2[1])

                if pair in before:
                    i1, i2 = i2, i1
                    pair = '%s | %s' % (i1[1], i2[1])

                if not pair in before or n_play == 0:
                    idle_clients.remove(i1)
                    idle_clients.remove(i2)

                    playing_clients.append((i1, i2))

                    t = threading.Thread(target=play_game, args=(i1, i2, tpm, time_buffer_soft, time_buffer_hard, ))
                    t.start()

                    before.append(pair)

                    while len(before) >= match_history_size:
                        del before[0]

                else:
                    flog('pair "%s" already in history' % pair)

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
            c.execute('INSERT INTO players(user, password, rating) VALUES(%s, %s, 1000)', (user, password,))
            conn.commit()
            conn.close()

        elif row[0] != password:
            sck.send(bytes('Invalid password\n', encoding='utf8'))
            sck.close()
            return

        e = ataxx.uai.Engine(sck, True)
        e.uai()
        e.isready()

        flog('Connected with %s (%s) running %s (by %s)' % (addr, user, e.name, e.author))

        conn = mysql.connector.connect(host=db_host, user=db_user, passwd=db_pass, database=db_db)
        c = conn.cursor()
        c.execute('UPDATE players SET author=%s, engine=%s WHERE user=%s', (e.author, e.name, user,))
        conn.commit()
        conn.close()

        with lock:
            for clnt in idle_clients:
                if clnt[1] == user:
                    flog('Removing duplicate user %s' % user)
                    idle_clients.remove(clnt)
                    clnt[0].quit()

            idle_clients.append((e, user))

    except Exception as e:
        flog('Fail: %s' % e)
        sck.close()
        traceback.print_exc(file=sys.stdout)

class http_server(BaseHTTPRequestHandler):
    def _set_headers(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()

    def do_GET(self):
        self._set_headers()

        flog('HTTP request for %s' % self.path)

        out = None

        if self.path == '/':
            out = '<h3>idle players</h3><table><tr><th>user</th><th>program</th></tr>'

            with lock:
                for clnt in idle_clients:
                    p1 = clnt[0]
                    p1_name = p1.name
                    p1_user = clnt[1]

                    out += '<tr><td>%s</td><td>%s</td></tr>' % (p1_user, p1_name)

            out += '</table>'

            out += '<h3>playing players</h3><table><tr><th>player 1</th><th>player 2</th></tr>'

            with lock:
                for couple in playing_clients:
                    clnt1 = couple[0]
                    p1 = clnt1[0]
                    p1_name = p1.name
                    p1_user = clnt1[1]

                    clnt2 = couple[1]
                    p2 = clnt2[0]
                    p2_name = p2.name
                    p2_user = clnt2[1]

                    out += '<tr><td>%s / %s</td><td>%s / %s</td></tr>' % (p1_user, p1_name, p2_user, p2_name)

            out += '</table>'

        elif self.path == '/json':
            idles = []

            with lock:
                for clnt in idle_clients:
                    p1 = clnt[0]
                    p1_name = p1.name
                    p1_user = clnt[1]

                    la = last_activity[p1_name] if p1_name in last_activity else 0
                    idles.append({ 'user' : p1_user, 'name' : p1_name, 'last_activity' : la })

            playing = []

            with lock:
                for couple in playing_clients:
                    clnt1 = couple[0]
                    p1 = clnt1[0]
                    p1_name = p1.name
                    p1_user = clnt1[1]

                    la1 = last_activity[p1_name] if p1_name in last_activity else 0

                    clnt2 = couple[1]
                    p2 = clnt2[0]
                    p2_name = p2.name
                    p2_user = clnt2[1]

                    la2 = last_activity[p2_name] if p2_name in last_activity else 0

                    playing.append({ 'player_1' : { 'user' : p1_user, 'name' : p1_name, 'last_activity' : la1 }, 'player_2' : { 'user' : p2_user, 'name' : p2_name, 'last_activity' : la2 } })

            temp = { 'idle' : idles, 'playing' : playing }

            out = json.dumps(temp)

        self.wfile.write(out.encode('utf8'))

    def do_HEAD(self):
        self._set_headers()

def run_httpd(server_class=ThreadingHTTPServer, handler_class=http_server, addr='localhost', port=http_port):
    server_address = (addr, port)
    httpd = server_class(server_address, handler_class)

    flog(f"Starting httpd server on {addr}:{port}")
    httpd.serve_forever()

idle_clients = []
playing_clients = []

t = threading.Thread(target=match_scheduler)
t.start()

t = threading.Thread(target=run_httpd)
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
    flog('tcp connection with %s %s ' % (cs, addr))

    cs.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

    t = threading.Thread(target=add_client, args=(cs,addr,))
    t.start()
