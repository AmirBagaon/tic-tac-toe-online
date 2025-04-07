import eventlet # Important for async_mode='eventlet'
eventlet.monkey_patch() # Patches standard libraries for compatibility

from flask import Flask, render_template, request # Import request
from flask_socketio import SocketIO, emit, join_room, leave_room

# --- App Initialization ---
app = Flask(__name__)
app.config['SECRET_KEY'] = 'your_secret_key_needs_changing!' # Change this!
socketio = SocketIO(app, async_mode='eventlet')

# --- Server State Management ---
players = {} # Maps player SID to player info {'name': name, 'room': room_id, 'symbol': 'X'/'O'}
games = {} # Maps room_id to game state {'board':[], 'currentPlayer':'X'/'O', 'players': [sid1, sid2], 'player_names': {sid1: name1, sid2: name2}, 'gameOver': False, 'winner': None}
waiting_player = None # Stores the SID of a player waiting for an opponent

# --- Utility Functions (check_winner, check_draw remain the same) ---
def check_winner(current_board):
    winning_combinations = [
        [0, 1, 2], [3, 4, 5], [6, 7, 8], # Rows
        [0, 3, 6], [1, 4, 7], [2, 5, 8], # Columns
        [0, 4, 8], [2, 4, 6]             # Diagonals
    ]
    for combo in winning_combinations:
        a, b, c = combo
        if current_board[a] and current_board[a] == current_board[b] == current_board[c]:
            return current_board[a]
    return None

def check_draw(current_board):
    return None not in current_board and check_winner(current_board) is None

# --- Flask Routes ---
@app.route('/')
def index():
    # No game reset here anymore, state is managed via connections
    return render_template('index.html')

# --- SocketIO Event Handlers ---

@socketio.on('connect')
def handle_connect():
    """Handles new client connections and performs matchmaking."""
    global waiting_player, players, games
    sid = request.sid
    player_name = request.args.get('name', 'Anonymous') # Get name from connection query
    if not player_name: player_name = 'Anonymous' # Ensure name isn't empty
    player_name = player_name[:20] # Limit name length

    print(f"Client connected! SID: {sid}, Name: {player_name}")

    # Store basic player info
    players[sid] = {'name': player_name, 'room': None, 'symbol': None}

    if waiting_player and waiting_player != sid:
        # --- Start a new game ---
        player1_sid = waiting_player
        player2_sid = sid
        room_id = f"game_{player1_sid[:4]}_{player2_sid[:4]}" # Create a unique room ID

        print(f"Pairing {players[player1_sid]['name']} (X) vs {players[player2_sid]['name']} (O) in room {room_id}")

        # Clear waiting player
        waiting_player = None

        # Update player records
        players[player1_sid]['room'] = room_id
        players[player1_sid]['symbol'] = 'X'
        players[player2_sid]['room'] = room_id
        players[player2_sid]['symbol'] = 'O'

        # Create game state
        games[room_id] = {
            'board': [None] * 9,
            'currentPlayer': 'X', # X always starts
            'players': [player1_sid, player2_sid],
            'player_names': {player1_sid: players[player1_sid]['name'], player2_sid: players[player2_sid]['name']},
            'gameOver': False,
            'winner': None
        }

        # Add players to the SocketIO room
        join_room(room_id, sid=player1_sid)
        join_room(room_id, sid=player2_sid)

        # Notify players game has started
        emit('game_start', {'symbol': 'X', 'opponentName': players[player2_sid]['name']}, room=player1_sid)
        emit('game_start', {'symbol': 'O', 'opponentName': players[player1_sid]['name']}, room=player2_sid)

        # Send initial game state to the room
        socketio.emit('update_game', games[room_id], to=room_id) # Use 'to' instead of 'room' for emit

    else:
        # --- Make player wait ---
        waiting_player = sid
        print(f"Player {player_name} ({sid}) is waiting.")
        emit('wait_for_opponent', room=sid) # Notify client they are waiting

@socketio.on('disconnect')
def handle_disconnect():
    """Handles client disconnections, cleans up games."""
    global waiting_player, players, games
    sid = request.sid
    print(f"Client disconnected. SID: {sid}")

    player = players.pop(sid, None) # Remove player and get their info

    if player: # If player was found
        room_id = player.get('room')
        if room_id and room_id in games:
            # Player was in a game
            print(f"Player {player['name']} left room {room_id}")
            leave_room(room_id, sid=sid) # Optional: remove from SocketIO room

            game = games[room_id]
            opponent_sid = None
            # Find opponent
            for p_sid in game['players']:
                if p_sid != sid:
                    opponent_sid = p_sid
                    break

            if opponent_sid and opponent_sid in players: # Check if opponent still connected
                # Notify opponent
                print(f"Notifying opponent {players[opponent_sid]['name']} ({opponent_sid})")
                emit('opponent_left', room=opponent_sid)
                # Remove room reference from opponent
                players[opponent_sid]['room'] = None
                # Set opponent as waiting? Or just let them disconnect/refresh? Let's make them wait.
                waiting_player = opponent_sid
                emit('wait_for_opponent', room=opponent_sid)


            # Delete the game room state
            print(f"Deleting game room {room_id}")
            del games[room_id]

        elif sid == waiting_player:
            # Player was waiting
            print(f"Player {player['name']} stopped waiting.")
            waiting_player = None
    else:
        print(f"Disconnected SID {sid} not found in players list.")


# --- Handle Player Moves ---
@socketio.on('make_move')
def handle_make_move(data):
    """Handles a move attempt from a client, validates, updates state, and broadcasts."""
    sid = request.sid
    print(f"Received move data from {sid}: {data}")

    player = players.get(sid)
    if not player:
        print(f"Error: Player not found for SID {sid}")
        emit('game_error', 'Player not recognized. Please refresh.', room=sid)
        return

    room_id = player.get('room')
    player_symbol = player.get('symbol')

    if not room_id or room_id not in games:
        print(f"Error: Player {player['name']} ({sid}) is not in an active game.")
        emit('game_error', 'You are not in an active game.', room=sid)
        return

    game = games[room_id]
    index = data.get('index')

    # --- Validation ---
    if game['gameOver']:
        print("Ignoring move: Game is over.")
        emit('game_error', 'Game is already over.', room=sid)
        return
    if game['currentPlayer'] != player_symbol:
        print(f"Ignoring move: Not player {player_symbol}'s turn (it's {game['currentPlayer']}'s turn).")
        emit('game_error', 'Not your turn.', room=sid)
        return
    if index is None or not (0 <= index < 9):
        print(f"Ignoring move: Invalid index {index}.")
        emit('game_error', 'Invalid cell index.', room=sid)
        return
    if game['board'][index] is not None:
        print(f"Ignoring move: Cell {index} is not empty.")
        emit('game_error', 'Cell already taken.', room=sid)
        return

    # --- Process Valid Move ---
    print(f"Processing move: Player {player_symbol} places on index {index} in room {room_id}")
    game['board'][index] = player_symbol

    # Check for winner
    winner = check_winner(game['board'])
    if winner:
        game['winner'] = winner
        game['gameOver'] = True
        print(f"Winner found: {winner} in room {room_id}")
    else:
        # Check for draw
        if check_draw(game['board']):
            game['winner'] = 'Draw'
            game['gameOver'] = True
            print(f"Game is a Draw in room {room_id}")
        else:
            # Switch player
            game['currentPlayer'] = 'O' if game['currentPlayer'] == 'X' else 'X'
            print(f"Turn switched to: {game['currentPlayer']} in room {room_id}")

    # Broadcast the updated game state to the specific room
    print(f"Broadcasting state to room {room_id}: {game}")
    socketio.emit('update_game', game, to=room_id) # Use 'to' for rooms


# --- Handle Chat Messages ---
@socketio.on('send_message')
def handle_send_message(data):
    """Relays chat messages to the correct game room."""
    sid = request.sid
    player = players.get(sid)

    if not player:
        print(f"Chat Error: Player not found for SID {sid}")
        return # Ignore message if player isn't registered

    room_id = player.get('room')
    player_name = player.get('name', 'Unknown')
    message_text = data.get('text', '').strip() # Get text, remove leading/trailing whitespace

    if not room_id or room_id not in games:
        print(f"Chat Info: Player {player_name} ({sid}) sent chat but is not in a room.")
        emit('game_error', 'You must be in a game to chat.', room=sid) # Notify sender
        return

    if not message_text:
        print(f"Chat Info: Player {player_name} sent empty message.")
        return # Ignore empty messages

    # Limit message length
    message_text = message_text[:200] # Limit chat message length

    print(f"Relaying message from {player_name} in room {room_id}: {message_text}")
    # Emit to the specific room, including the sender's name
    socketio.emit('new_message', {
        'sender': player_name,
        'text': message_text
    }, to=room_id)


# --- Run the Application ---
if __name__ == '__main__':
    print("Starting Flask-SocketIO server locally (use Gunicorn in production)...")
    socketio.run(app, host='0.0.0.0', port=5000, debug=False)