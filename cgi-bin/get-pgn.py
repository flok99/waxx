#! /usr/bin/python3

import ataxx
import ataxx.pgn

import cgi
import mysql.connector

db_host = '192.168.64.1'
db_user = 'user'
db_pass = 'pass'
db_db = 'waxx'

form = cgi.FieldStorage()
md5 = form.getvalue('md5')

conn = mysql.connector.connect(host=db_host, user=db_user, passwd=db_pass, database=db_db)
c = conn.cursor()
c.execute('SELECT pgn, p1, p2 FROM results WHERE md5=%s', (md5,))
row = c.fetchone()
conn.commit()
conn.close()

print('Content-Type: text/plain\r\n\r')

print('player1 %s' % row[1])
print('player2 %s' % row[2])

for game in ataxx.pgn.GameIterator(row[0], is_string=True):
    if 'FEN' in game.headers:
        b = ataxx.Board(game.headers['FEN'])
    else:
        b = ataxx.Board()

    print('START %s' % b.get_fen())

    for node in game.main_line():
        b.makemove(node.move)
        print('%s %s' % (node.move, b.get_fen()))
    break
