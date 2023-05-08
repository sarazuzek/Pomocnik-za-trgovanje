from bottleext import get, post, run, request, template, redirect, static_file, url

from auth_public import *

import psycopg2, psycopg2.extensions, psycopg2.extras
psycopg2.extensions.register_type(psycopg2.extensions.UNICODE)

import os

import re

import csv

from Podatki import get_history as gh

import hashlib

# privzete nastavitve
SERVER_PORT = os.environ.get('BOTTLE_PORT', 8080)
RELOADER = os.environ.get('BOTTLE_RELOADER', True)
DB_PORT = os.environ.get('POSTGRES_PORT', 5432)

# PRIKLOP NA BAZO
conn = psycopg2.connect(database=db, host=host, user=user, password=password, port=DB_PORT)
cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor) 

# odkomentiraj, če želiš sporočila o napakah
# debug(True)

@get('/static/<filename:path>')
def static(filename):
   return static_file(filename, root='static')

user_ime = ""
uspesna_prijava = True        
sporocilo = ""
user_id = 0
pravilen_simbol = True
uspesna_registracija = True

########################### Prijava in registracija ###########################
@get('/')
def zacetna_stran():
    return template('home.html', pair=cur)

@post('/prijava')
def prijava_post():
    uporabnisko_ime = request.forms.getunicode("ime")
    geslo = request.forms.getunicode('geslo')
    global uspesna_prijava, sporocilo, user_id, user_ime
    row = cur.execute("SELECT DISTINCT id_user, name FROM app_user WHERE user_name = '{0}' and password = '{1}'".format(uporabnisko_ime, geslo))
    row = cur.fetchone()
    if row != None:
        user_id = row[0]
        user_ime = row[1]
        sporocilo = ""
        redirect(url('/uporabnik'))
    else:
        uspesna_prijava = False
        sporocilo = "Napačno uporabinško ime ali geslo!"
        redirect(url('/'))

@get('/registracija')
def registracija_get():
    return template('registracija.html', naslov = "Registracija")

@post('/registracija')
def registracija_post():
    ime = request.forms.name
    priimek = request.forms.surname
    datum_rojstva = request.forms.date_of_birth
    uporabnisko_ime = request.forms.user_name
    geslo = request.forms.password
    global uspesna_registracija, sporocilo
    row = cur.execute("SELECT name FROM app_user WHERE user_name = '{}'".format(uporabnisko_ime))
    row = cur.fetchone()
    if row != None:
        uspesna_registracija = False
        sporocilo = "Registracija ni možna, to uporabniško ime že obstaja."
        redirect('/registracija')
    else:
        cur.execute("INSERT INTO app_user (name, surname, date_of_birth, user_name, password) VALUES (%s, %s, %s, %s, %s) RETURNING id_user",
                (ime, priimek, datum_rojstva, uporabnisko_ime, geslo))
        conn.commit()
        sporocilo = ""
        redirect('/uporabnik')

#############################################################################
@get('/pairs')
def pairs():
    cur.execute("SELECT symbol, name FROM pair")
    return template('pairs.html', pair=cur)

"""SELECT app_user.name, symbol_id, amount FROM asset 
    INNER JOIN app_user ON user_id = id_user 
    ORDER BY app_user.name """

@get('/uporabnik')
def uporabnik():
    return template('uporabnik.html', uporabnik=cur)

########################### Pari-dodajanje ###########################
@get('/dodaj')
def dodaj():
    global sporocilo
    sporocilo = ""
    cur.execute("""
      SELECT symbol,name from pair
   """)
    return template('dodaj_par.html', pair=cur)

@post('/dodaj_potrdi')
def dodaj_potrdi():
    global pravilen_simbol, sporocilo
    symbol = request.forms.symbol
    name = request.forms.ime
    if gh.preveri_ustreznost('{}'.format(symbol)) == 0:
        pravilen_simbol = False
        sporocilo = "Vnešen napačen simbol"
        redirect(url('/dodaj'))
    else:
        cur.execute("INSERT INTO pair (symbol, name) VALUES (%s, %s)", (symbol, name))
        conn.commit()
        gh.get_historic_data(['{}'.format(symbol)])
        uvozi_Price_History('{}.csv'.format(symbol))
        pravilen_simbol = True
        sporocilo = "Simbol uspešno dodan"
        redirect(url('/dodaj'))

def uvozi_Price_History(tabela):
    # ce uvozim iz uvoz_podatkov vrne error 'no module named auth'
    with open('Podatki/Posamezni_simboli/{0}'.format(tabela)) as csvfile:
        podatki = csv.reader(csvfile)
        next(podatki)
        for r in podatki:
            r = [None if x in ('', '-') else x for x in r]
            cur.execute("""
                INSERT INTO price_history
                (symbol_id, date, price)
                VALUES (%s, %s, %s)
            """, r)
        conn.commit()
        print("Uspesno uvozil csv datoteko!")

#############################################################################
######################## Assets - pregled, dodajanje ########################
@get('/assets')
def asset():
    cur.execute("""SELECT symbol_id, amount FROM asset 
    WHERE user_id = {} ORDER BY amount """.format(user_id))
    return template('assets.html', asset=cur)

@post('/buy_sell')
def buy_sell():
    global sporocilo
    symbol = request.forms.symbol
    datum = request.forms.datum
    tip = request.forms.tip
    amount = request.forms.amount
    amount = float(amount)
    amount = sign(amount, tip)
    check_user(user_id)
    row = cur.execute("SELECT  symbol FROM pair WHERE symbol = '{}'".format(symbol))
    row = cur.fetchone()
    if row != None:
        cur.execute("INSERT INTO trade (user_id, symbol_id, type, date, pnl) VALUES (%s, %s, %s, %s, %s) RETURNING id_trade",
                    (user_id, symbol, tip, datum, amount))
        conn.commit()
        trade = [user_id, symbol, float(amount)]
        trade_result(trade)
        sporocilo = "Transakcija potrjena"
        redirect(url('/assets'))
    else:
        sporocilo = "Napačen simbol!"
        redirect(url('/assets'))

def sign(amount: float, bs):
    if bs == 'Buy':
        return abs(amount)
    elif bs == 'Sell':
         return -abs(amount)
    else:
        return print(bs)

def trade_result(trade):
    uid = trade[0]
    simbol = trade[1]
    pnl = trade[2]
    row = cur.execute("SELECT amount FROM asset WHERE user_id = '{0}' AND symbol_id = '{1}'".format(uid, simbol))
    row = cur.fetchone()
    if row == None:
        cur.execute("INSERT INTO asset (user_id, symbol_id, amount) VALUES (%s, %s, %s)", (uid, simbol, pnl))
    else:
        amount = round(pnl + float(row[0]), 2)
        cur.execute("UPDATE  asset SET amount = {0} WHERE user_id = '{1}' AND symbol_id = '{2}'".format(amount, uid, simbol))
    conn.commit()

def check_user(user_id):
    if user_id > 0:
        pass
    else:
        print('user_id is still 0')
        ValueError
    
#############################################################################
######################## Trades - pregled, dodajanje ########################
@get('/trades')
def trades():
    cur.execute("""SELECT symbol_id, type, strategy, RR, target, date, duration, TP, PNL FROM trade
    WHERE user_id = {} ORDER BY symbol_id """.format(user_id))
    return template('trades.html', trade=cur)

@get('/performance')
def performance():
    return template('performance.html')




#############################################################################
if __name__ == "__main__":
    run(host='localhost', port=8080, reloader=True)