from flask import Flask, render_template, request, redirect, url_for, session
import sqlite3

app = Flask(__name__)
app.secret_key = 'med_app_secret'


# --- DATABASE SETUP ---
def get_db_connection():
    conn = sqlite3.connect('pharmacy.db')
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS shops 
                      (shop_id TEXT PRIMARY KEY, name TEXT, location TEXT, password TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS inventory 
                      (id INTEGER PRIMARY KEY AUTOINCREMENT, shop_id TEXT, 
                       med_name TEXT, stock_count INTEGER, price REAL DEFAULT 0.0)''')

    cursor.execute("PRAGMA table_info(inventory)")
    columns = [column[1] for column in cursor.fetchall()]
    if 'price' not in columns:
        cursor.execute("ALTER TABLE inventory ADD COLUMN price REAL DEFAULT 0.0")

    cursor.execute(
        "INSERT OR IGNORE INTO shops VALUES ('shop101', 'City Pharmacy', 'https://goo.gl/maps/example', '1234')")
    conn.commit()
    conn.close()


init_db()


# --- HELPER FUNCTIONS ---
def get_all_medicine_names():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT med_name FROM inventory")
    meds = [row['med_name'] for row in cursor.fetchall()]
    conn.close()
    return meds


# --- USER ROUTES ---
@app.route('/')
def index():
    query = request.args.get('search', '').lower()
    results = []
    all_meds = get_all_medicine_names()
    if query:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''SELECT shops.name, inventory.med_name, inventory.stock_count, shops.location, inventory.price 
                          FROM inventory JOIN shops ON inventory.shop_id = shops.shop_id 
                          WHERE inventory.med_name LIKE ?''', ('%' + query + '%',))
        results = cursor.fetchall()
        conn.close()
    return render_template('index.html', results=results, all_meds=all_meds)


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        sid, pwd = request.form['shop_id'], request.form['password']
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM shops WHERE shop_id=? AND password=?", (sid, pwd))
        user = cursor.fetchone()
        conn.close()
        if user:
            session['shop_id'] = sid
            return redirect(url_for('dashboard'))
    return render_template('login.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        sid, name, loc, pwd = request.form['shop_id'], request.form['name'], request.form['location'], request.form[
            'password']
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("INSERT INTO shops (shop_id, name, location, password) VALUES (?, ?, ?, ?)",
                           (sid, name, loc, pwd))
            conn.commit()
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            return "Error: This Shop ID is already taken."
        finally:
            conn.close()
    return render_template('register.html')


# --- OWNER DASHBOARD ---
@app.route('/dashboard', methods=['GET', 'POST'])
def dashboard():
    if 'shop_id' not in session:
        return redirect(url_for('login'))

    sid = session['shop_id']
    conn = get_db_connection()

    if request.method == 'POST':
        form_type = request.form.get('form_type')
        med = request.form['med_name'].lower()

        # 1. ADD NEW PRODUCT
        if form_type == 'add':
            qty = int(request.form['stock'])
            price = float(request.form.get('price', 0.0))
            conn.execute("INSERT OR REPLACE INTO inventory (shop_id, med_name, stock_count, price) VALUES (?, ?, ?, ?)",
                         (sid, med, qty, price))

        # 2. UPDATE STOCK LEVEL
        elif form_type == 'update_stock':
            new_qty = int(request.form['stock'])
            conn.execute("UPDATE inventory SET stock_count=? WHERE shop_id=? AND med_name=?",
                         (new_qty, sid, med))

        # 3. UPDATE PRICE LEVEL
        elif form_type == 'update_price':
            new_price = float(request.form['price'])
            conn.execute("UPDATE inventory SET price=? WHERE shop_id=? AND med_name=?",
                         (new_price, sid, med))

        conn.commit()

    shop_data = conn.execute("SELECT name FROM shops WHERE shop_id = ?", (sid,)).fetchone()
    stocks = conn.execute("SELECT med_name, stock_count, price FROM inventory WHERE shop_id=?", (sid,)).fetchall()
    conn.close()
    return render_template('dashboard.html', stocks=stocks, shop_name=shop_data['name'])


# --- NEW: SHOW INVENTORY ---
@app.route('/inventory_list')
def inventory_list():
    if 'shop_id' not in session:
        return redirect(url_for('login'))

    sid = session['shop_id']
    conn = get_db_connection()

    # Fetch shop details
    shop_info = conn.execute("SELECT name, shop_id FROM shops WHERE shop_id = ?", (sid,)).fetchone()

    # Fetch all medicines for this shop
    inventory_items = conn.execute(
        "SELECT med_name, stock_count, price FROM inventory WHERE shop_id = ?", (sid,)
    ).fetchall()

    conn.close()
    return render_template('inventory_list.html', shop=shop_info, items=inventory_items)


# --- BILLING ---
@app.route('/billing', methods=['GET', 'POST'])
def billing():
    if 'shop_id' not in session:
        return redirect(url_for('login'))

    sid = session['shop_id']
    conn = get_db_connection()

    shop_info = conn.execute("SELECT name FROM shops WHERE shop_id = ?", (sid,)).fetchone()
    shop_name = shop_info['name'] if shop_info else "Unknown Shop"

    if request.method == 'POST':
        med_names = request.form.getlist('med_name[]')
        quantities = request.form.getlist('quantity[]')

        for name, qty in zip(med_names, quantities):
            if name and qty:
                conn.execute(
                    "UPDATE inventory SET stock_count = MAX(0, stock_count - ?) WHERE shop_id = ? AND med_name = ?",
                    (int(qty), sid, name.lower()))
        conn.commit()
        conn.close()
        return redirect(url_for('dashboard'))

    cursor = conn.execute(
        "SELECT med_name, price, stock_count FROM inventory WHERE shop_id = ? AND stock_count > 0",
        (sid,)
    )
    available_items = cursor.fetchall()
    conn.close()
    return render_template('billing.html', available_items=available_items, shop_name=shop_name, shop_id=sid)


# --- ACTIONS ---
@app.route('/increase_stock_one/<med_name>')
def increase_stock_one(med_name):
    if 'shop_id' in session:
        conn = get_db_connection()
        conn.execute("UPDATE inventory SET stock_count = stock_count + 1 WHERE shop_id = ? AND med_name = ?",
                     (session['shop_id'], med_name))
        conn.commit()
        conn.close()
    return redirect(url_for('dashboard'))


@app.route('/decrease_stock_one/<med_name>')
def decrease_stock_one(med_name):
    if 'shop_id' in session:
        conn = get_db_connection()
        conn.execute("UPDATE inventory SET stock_count = MAX(0, stock_count - 1) WHERE shop_id = ? AND med_name = ?",
                     (session['shop_id'], med_name))
        conn.commit()
        conn.close()
    return redirect(url_for('dashboard'))


@app.route('/delete_medicine/<med_name>')
def delete_medicine(med_name):
    if 'shop_id' in session:
        conn = get_db_connection()
        conn.execute("DELETE FROM inventory WHERE shop_id = ? AND med_name = ?", (session['shop_id'], med_name))
        conn.commit()
        conn.close()
    return redirect(url_for('dashboard'))


@app.route('/delete_shop_record')
def delete_shop_record():
    if 'shop_id' in session:
        sid = session['shop_id']
        conn = get_db_connection()
        conn.execute("DELETE FROM inventory WHERE shop_id=?", (sid,))
        conn.execute("DELETE FROM shops WHERE shop_id=?", (sid,))
        conn.commit()
        conn.close()
        session.clear()
        return redirect(url_for('index'))
    return "Unauthorized", 401


if __name__ == '__main__':
    app.run(debug=True)