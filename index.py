from flask import Flask, request, jsonify
from flask_cors import CORS
from supabase import create_client
import os
from datetime import datetime

app = Flask(__name__)
CORS(app)

# Get from environment variables
SUPABASE_URL = os.environ.get('SUPABASE_URL')
SUPABASE_KEY = os.environ.get('SUPABASE_ANON_KEY')

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

def token_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('Authorization')
        if not token:
            return jsonify({'error': 'Token missing'}), 401
        token = token.replace('Bearer ', '')
        try:
            user = supabase.auth.get_user(token)
            request.current_user = user.user
        except:
            return jsonify({'error': 'Invalid token'}), 401
        return f(*args, **kwargs)
    return decorated

@app.route('/api/auth/signup', methods=['POST'])
def signup():
    data = request.json
    try:
        response = supabase.auth.sign_up({
            'email': data['email'],
            'password': data['password'],
            'options': {'data': {'username': data['username']}}
        })
        return jsonify({
            'token': response.session.access_token,
            'user': response.user
        }), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/api/auth/login', methods=['POST'])
def login():
    data = request.json
    try:
        response = supabase.auth.sign_in_with_password({
            'email': data['email'],
            'password': data['password']
        })
        return jsonify({
            'token': response.session.access_token,
            'user': response.user
        })
    except:
        return jsonify({'error': 'Invalid credentials'}), 401

@app.route('/api/accounts', methods=['GET'])
@token_required
def get_accounts():
    response = supabase.table('accounts').select('*').eq('user_id', request.current_user.id).execute()
    return jsonify(response.data)

@app.route('/api/accounts', methods=['POST'])
@token_required
def create_account():
    data = request.json
    response = supabase.table('accounts').insert({
        'user_id': request.current_user.id,
        'name': data['name'],
        'type': data.get('type', 'bank'),
        'balance': data.get('balance', 0),
        'currency': data.get('currency', 'USD')
    }).execute()
    return jsonify(response.data[0]), 201

@app.route('/api/accounts/<int:account_id>', methods=['DELETE'])
@token_required
def delete_account(account_id):
    supabase.table('accounts').delete().eq('id', account_id).eq('user_id', request.current_user.id).execute()
    return jsonify({'message': 'Deleted'})

@app.route('/api/categories', methods=['GET'])
@token_required
def get_categories():
    response = supabase.table('categories').select('*').eq('user_id', request.current_user.id).execute()
    return jsonify(response.data)

@app.route('/api/categories', methods=['POST'])
@token_required
def create_category():
    data = request.json
    response = supabase.table('categories').insert({
        'user_id': request.current_user.id,
        'name': data['name'],
        'type': data['type'],
        'color': data.get('color', '#6c5ce7')
    }).execute()
    return jsonify(response.data[0]), 201

@app.route('/api/transactions', methods=['GET'])
@token_required
def get_transactions():
    query = supabase.table('transactions').select('*').eq('user_id', request.current_user.id)
    if request.args.get('type'):
        query = query.eq('type', request.args.get('type'))
    response = query.order('transaction_date', desc=True).execute()
    return jsonify(response.data)

@app.route('/api/transactions', methods=['POST'])
@token_required
def create_transaction():
    data = request.json
    # Update account balance
    account = supabase.table('accounts').select('balance').eq('id', data['account_id']).eq('user_id', request.current_user.id).execute()
    if not account.data:
        return jsonify({'error': 'Account not found'}), 404
    current = account.data[0]['balance']
    new_balance = current + data['amount'] if data['type'] == 'income' else current - data['amount']
    supabase.table('accounts').update({'balance': new_balance}).eq('id', data['account_id']).execute()
    # Create transaction
    response = supabase.table('transactions').insert({
        'user_id': request.current_user.id,
        'account_id': data['account_id'],
        'category_id': data.get('category_id'),
        'amount': data['amount'],
        'type': data['type'],
        'description': data.get('description', ''),
        'transaction_date': data['transaction_date']
    }).execute()
    return jsonify({'id': response.data[0]['id']}), 201

@app.route('/api/transactions/<int:transaction_id>', methods=['DELETE'])
@token_required
def delete_transaction(transaction_id):
    transaction = supabase.table('transactions').select('*').eq('id', transaction_id).eq('user_id', request.current_user.id).execute()
    if not transaction.data:
        return jsonify({'error': 'Not found'}), 404
    t = transaction.data[0]
    account = supabase.table('accounts').select('balance').eq('id', t['account_id']).execute()
    if account.data:
        current = account.data[0]['balance']
        new_balance = current - t['amount'] if t['type'] == 'income' else current + t['amount']
        supabase.table('accounts').update({'balance': new_balance}).eq('id', t['account_id']).execute()
    supabase.table('transactions').delete().eq('id', transaction_id).execute()
    return jsonify({'message': 'Deleted'})

@app.route('/api/transfers', methods=['POST'])
@token_required
def create_transfer():
    data = request.json
    from_account = supabase.table('accounts').select('name, balance').eq('id', data['from_account_id']).eq('user_id', request.current_user.id).execute()
    to_account = supabase.table('accounts').select('name').eq('id', data['to_account_id']).eq('user_id', request.current_user.id).execute()
    if not from_account.data or from_account.data[0]['balance'] < data['amount']:
        return jsonify({'error': 'Insufficient funds'}), 400
    supabase.table('accounts').update({'balance': from_account.data[0]['balance'] - data['amount']}).eq('id', data['from_account_id']).execute()
    to_balance = supabase.table('accounts').select('balance').eq('id', data['to_account_id']).execute().data[0]['balance']
    supabase.table('accounts').update({'balance': to_balance + data['amount']}).eq('id', data['to_account_id']).execute()
    supabase.table('transactions').insert([
        {'user_id': request.current_user.id, 'account_id': data['from_account_id'], 'amount': data['amount'], 'type': 'expense', 'description': f"Transfer to {to_account.data[0]['name']}", 'transaction_date': data['transaction_date']},
        {'user_id': request.current_user.id, 'account_id': data['to_account_id'], 'amount': data['amount'], 'type': 'income', 'description': f"Transfer from {from_account.data[0]['name']}", 'transaction_date': data['transaction_date']}
    ]).execute()
    return jsonify({'message': 'Transfer completed'}), 201

@app.route('/api/dashboard/stats', methods=['GET'])
@token_required
def get_dashboard_stats():
    accounts = supabase.table('accounts').select('balance').eq('user_id', request.current_user.id).execute()
    total_balance = sum(a['balance'] for a in accounts.data)
    start_of_month = datetime.now().replace(day=1).strftime('%Y-%m-%d')
    transactions = supabase.table('transactions').select('type, amount').eq('user_id', request.current_user.id).gte('transaction_date', start_of_month).execute()
    monthly_income = sum(t['amount'] for t in transactions.data if t['type'] == 'income')
    monthly_expense = sum(t['amount'] for t in transactions.data if t['type'] == 'expense')
    recent = supabase.table('transactions').select('*').eq('user_id', request.current_user.id).order('transaction_date', desc=True).limit(10).execute()
    return jsonify({
        'total_balance': total_balance,
        'monthly_income': monthly_income,
        'monthly_expense': monthly_expense,
        'recent_transactions': recent.data
    })

# Vercel handler
def handler(event, context):
    return app(event, context)

if __name__ == '__main__':
    app.run()