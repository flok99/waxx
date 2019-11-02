#! /usr/bin/python3

import asyncio
import hashlib
import json
import logging
import mysql.connector
import queue
import random
from random import randint
import socket
import sys
import threading
import time
import traceback
import websockets

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
ws_port = 7624
ws_interface = '127.0.0.1'

# match history
match_history_size = 25

logfile = 'waxx.log'

###

logger = logging.getLogger('websockets.server')
logger.setLevel(logging.ERROR)
logger.addHandler(logging.FileHandler(logfile))

ws_data = {}
ws_data_lock = threading.Lock()

async def ws_serve(websocket, path):
    global ws_data
    global ws_data_lock

    try:
        remote_ip = websocket.remote_address[0]
        flog('Websocket started for %s' % remote_ip)

        listen_pair = await websocket.recv()
        flog('Websocket is listening for %s' % listen_pair)

        p_np = p_fen = None

        while True:
            send = send_np = None

            with ws_data_lock:
                if p_fen == None or ws_data[listen_pair] != p_fen:
                    send = p_fen = ws_data[listen_pair]

                if p_np == None or ws_data['new_pair'] != p_np:
                    send_np = p_np = ws_data['new_pair']

            if send:
                await websocket.send('fen %s %s %f' % (send[0], send[1], send[2]))

            if send_np:
                await websocket.send('new_pair %s %s %f' % (send_np[0], send_np[1], send_np[2]))

            await asyncio.sleep(0.25)

    except websockets.exceptions.ConnectionClosedOK:
        flog('ws_serve: socket disconnected')

    except Exception as e:
        flog('ws_serve: %s' % e)
        fh = open(logfile, 'a')
        traceback.print_exc(file=fh)
        fh.close()

def run_websockets_server():
    start_server = websockets.serve(ws_serve, ws_interface, ws_port)

    asyncio.get_event_loop().run_until_complete(start_server)
    asyncio.get_event_loop().run_forever()

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
    c.execute('CREATE TABLE results(id INT(12) NOT NULL AUTO_INCREMENT, ts datetime, p1 varchar(64), e1 varchar(128), t1 double, p2 varchar(64), e2 varchar(128), t2 double, result varchar(7), adjudication varchar(128), plies int, tpm int, pgn text, md5 char(32), score int, primary key(id))')
    c.execute('CREATE TABLE players(user varchar(64), password varchar(64), author varchar(128), engine varchar(128), rating double default 1000, w int(8) default 0, d int(8) default 0, l int(8) default 0, failure_count int(8) default 0, primary key(user))')
    c.execute('create table moves(results_id int not null, move_nr int(4), fen varchar(128), move varchar(5), took double, score int, is_p1 int(1), foreign key(results_id) references results(id) )')
    conn.commit()
    conn.close()
except Exception as e:
    flog('db create: %s' % e)

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

        flog(' *** Starting game between %s(%s) and %s(%s)' % (p1.name, p1_user, p2.name, p2_user))

        pair = '%s|%s' % (p1_user, p2_user)

        with ws_data_lock:
            ws_data['new_pair'] = (p1_user, p2_user, time.time())

        p1.uainewgame()
        p1.setoption('UCI_Opponent', 'none none computer %s' % p2.name)
        p2.uainewgame()
        p2.setoption('UCI_Opponent', 'none none computer %s' % p1.name)

        pos = random.choice(book_lines)

        board = ataxx.Board(pos)

        reason = None

        n_ply = t1 = t2 = 0

        moves = []

        while not board.gameover():
            start = time.time()
            took = None

            who = p1.name if board.turn == ataxx.BLACK else p2.name
            side = "black" if board.turn == ataxx.BLACK else "white"

            maxwait = (t + time_buffer_hard) / 1000.0

            bestmove = ponder = None

            m = {}
            m['move_nr'] = board.fullmove_clock
            m['fen'] = board.get_fen()
            m['is_p1'] = 1 if board.turn == ataxx.BLACK else 0

            now = None

            if board.turn == ataxx.BLACK:
                p1.position(board.get_fen())

                try:
                    bestmove, ponder = p1.go(movetime=t, maxwait=maxwait)
                except Exception as e:
                    flog('p1.go threw %s' % e)

                if bestmove == None:
                    fail1 = True

                    try:
                        p1.quit()
                    except:
                        pass

                now = time.time()
                took = now - start
                t1 += took

                with lock:
                    last_activity[p1.name] = now

            else:
                p2.position(board.get_fen())

                try:
                    bestmove, ponder = p2.go(movetime=t, maxwait=maxwait)
                except Exception as e:
                    flog('p2.go threw %s' % e)

                if bestmove == None:
                    fail2 = True

                    try:
                        p2.quit()
                    except:
                        pass

                now = time.time()
                took = now - start
                t2 += took

                with lock:
                    last_activity[p2.name] = now

            t_left = t + time_buffer_soft - took * 1000
            if t_left < 0 and reason == None:
                reason = '%s used too much time (W)' % side
                flog('%s used %fms too much time' % (who, -t_left))

                if t + time_buffer_hard - took * 1000 < 0:
                    reason = '%s used too much time (F)' % side
                    flog('%s went over the hard limit' % side)
                    break

            if bestmove == None:
                if reason == None:
                    reason = '%s disconnected' % side
                break

            else:
                m['move'] = bestmove
                m['took'] = took

            n_ply += 1

            flog('%s) %s => %s (%f)' % (who, board.get_fen(), bestmove, took))
            move = ataxx.Move.from_san(bestmove)

            if board.is_legal(move) == False:
                who = p1.name if board.turn == ataxx.BLACK else p2.name
                reason = 'Illegal move by %s' % side
                flog('Illegal move by %s: %s' % (who, bestmove))

                if board.turn == ataxx.BLACK:
                    fail1 = True
                else:
                    fail2 = True

                m['score'] = -9999
                moves.append(m)
                break

            board.makemove(move)

            m['score'] = board.score()

            with ws_data_lock:
                ws_data[pair] = (board.get_fen(), bestmove, now)

            moves.append(m)

            if board.fifty_move_draw():
                reason = 'fifty moves'
                break

            #if board.max_length_draw(): FIXME
            #    reason = 'max length'
            #    break

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

            c = conn.cursor()
            c.execute("INSERT INTO results(ts, p1, e1, t1, p2, e2, t2, result, adjudication, plies, tpm, pgn, md5, score) VALUES(NOW(), %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)", (p1_user, p1.name, t1, p2_user, p2.name, t2, board.result(), adjudication, n_ply, t, pgn, hash_, board.score()))
            id_ = c.lastrowid

            c = conn.cursor()

            for m in moves:
                c.execute('INSERT INTO moves(results_id, move_nr, fen, move, took, score, is_p1) VALUES(%s, %s, %s, %s, %s, %s, %s)', (id_, m['move_nr'], m['fen'], m['move'], m['took'], m['score'], m['is_p1']))

            # update rating of the user
            if not fail1 and not fail2:
                i = elopy.Implementation()

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

                del i

            conn.commit()
            conn.close()

    except Exception as e:
        flog('failure: %s' % e)
        fh = open(logfile, 'a')
        traceback.print_exc(file=fh)
        fh.close()

        with lock:
            playing_clients.remove((p1_in, p2_in))

        fail1 = fail2 = True

    try:
        if fail1:
            p1_in[0].quit()
            del p1_in
    except:
        pass

    try:
        if fail2:
            p2_in[0].quit()
            del p2_in
    except:
        pass

# https://stackoverflow.com/questions/14992521/python-weighted-random
def weighted_random(pairs):
    total = sum(pair[0] for pair in pairs)

    r = randint(1, total)

    for(weight, value) in pairs:
        r -= weight

        if r <= 0:
            return value

def select_client(idle_clients, first):
    pairs = []

    conn = mysql.connector.connect(host=db_host, user=db_user, passwd=db_pass, database=db_db)
    c = conn.cursor()

    c.execute('SELECT MAX(rating) AS max_rating FROM players')
    max_ = c.fetchone()[0]

    c.execute('SELECT rating FROM players WHERE user=%s', (first[1],))
    first_rating = c.fetchone()[0]

    for client in idle_clients:
        c.execute('SELECT rating FROM players WHERE user=%s', (client[1],))
        row = c.fetchone()

        pairs.append((round(max_ - abs(first_rating - row[0])), client))

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
                    i1 = random.choice(idle_clients)

                    if len(idle_clients) > 2:
                        i2 = select_client(idle_clients, i1)
                    else:
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

def client_listener():
    HOST = ''
    PORT = 28028
    ss = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    ss.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    ss.bind((HOST, PORT))
    ss.listen(128)

    while True:
        cs, addr = ss.accept()
        flog('tcp connection with %s %s ' % (cs, addr))

        cs.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

        t = threading.Thread(target=add_client, args=(cs,addr,))
        t.start()


idle_clients = []
playing_clients = []

t = threading.Thread(target=match_scheduler)
t.start()

t = threading.Thread(target=run_httpd)
t.start()

t = threading.Thread(target=client_listener)
t.start()

run_websockets_server()
