// Wait for the HTML document to be fully loaded
document.addEventListener('DOMContentLoaded', () => {
    console.log('Document loaded.');

    // --- Global Variables ---
    let socket = null;
    let myPlayerSymbol = '?';
    let myName = '';
    let opponentName = '?';

    // Client-side Game State
    let localBoard = Array(9).fill(null);
    let localCurrentPlayer = '?';
    let localGameOver = false;

    // --- Get HTML Elements ---
    const nameInputSection = document.getElementById('name-input-section');
    const playerNameInput = document.getElementById('player-name');
    const joinButton = document.getElementById('join-button');
    const joinErrorElement = document.getElementById('join-error');

    const gameSection = document.getElementById('game-section');
    const myInfoElement = document.getElementById('my-info');
    const opponentInfoElement = document.getElementById('opponent-info');
    const boardElement = document.getElementById('board');
    const cells = document.querySelectorAll('.cell');
    const statusElement = document.getElementById('status');

    const chatArea = document.getElementById('chat-area');
    const chatMessages = document.getElementById('chat-messages');
    const chatInput = document.getElementById('chat-input');
    const sendChatButton = document.getElementById('send-chat-button');

    // --- Event Listener for Join Button ---
    joinButton.addEventListener('click', handleJoinGame);
    playerNameInput.addEventListener('keypress', (event) => {
        if (event.key === 'Enter') {
            handleJoinGame();
        }
    });

    function handleJoinGame() {
        const name = playerNameInput.value.trim();
        if (!name) {
            joinErrorElement.textContent = 'Please enter your name.';
            return;
        }
        if (name.length > 20) {
             joinErrorElement.textContent = 'Name cannot exceed 20 characters.';
             return;
        }
        joinErrorElement.textContent = '';
        myName = name;

        nameInputSection.style.display = 'none';
        gameSection.style.display = 'flex';
        statusElement.textContent = 'Status: Connecting...';

        connectWebSocket();
    }

    // --- WebSocket Connection Function ---
    function connectWebSocket() {
        if (socket) {
            socket.disconnect();
        }
        // Pass name in query
        socket = io({
            query: { name: myName }
        });
        setupSocketListeners();
    }


    // --- Setup Socket Listeners ---
    function setupSocketListeners() {
        socket.on('connect', () => {
            console.log('Connected to server!', socket.id);
            // Status set by 'wait' or 'game_start'
        });

        socket.on('connect_error', (err) => {
            console.error('Connection Failed:', err.message);
            statusElement.textContent = 'Status: Connection Failed. Refresh.';
            gameSection.style.display = 'none';
            nameInputSection.style.display = 'flex';
            joinErrorElement.textContent = 'Could not connect to server.';
            if (socket) socket.disconnect();
            socket = null;
        });


        socket.on('disconnect', () => {
            console.log('Disconnected from server.');
            statusElement.textContent = 'Status: Disconnected. Refresh to rejoin.';
            localGameOver = true;
        });

        // Handle being told to wait
        socket.on('wait_for_opponent', () => {
            console.log('Waiting for an opponent.');
            statusElement.textContent = 'Status: Waiting for opponent...';
            opponentInfoElement.textContent = 'Opponent: Waiting...';
             // Use backticks ` ` here
            myInfoElement.textContent = `You: ${myName} (?)`;
        });

        // Handle game starting
        socket.on('game_start', (data) => {
            console.log('Game starting!', data);
            myPlayerSymbol = data.symbol; // 'X' or 'O'
            opponentName = data.opponentName;
             // Use backticks ` ` here
            myInfoElement.textContent = `You: ${myName} (${myPlayerSymbol})`;
            opponentInfoElement.textContent = `Opponent: ${opponentName}`;
            statusElement.textContent = "Status: Game started!";
            // Server will send 'update_game' immediately after this usually
        });

        // Handle opponent disconnecting
         socket.on('opponent_left', () => {
             console.log('Opponent left the game.');
             statusElement.textContent = 'Status: Opponent disconnected. Game over.';
             localGameOver = true;
             opponentInfoElement.textContent = 'Opponent: Left';
             // Maybe disable board explicitly here if not done by redraw
             boardElement.style.pointerEvents = 'none';
         });


        // Handle Game State Updates
        socket.on('update_game', (gameState) => {
            console.log('Received game state update:', gameState);
            localBoard = gameState.board;
            localCurrentPlayer = gameState.currentPlayer;
            localGameOver = gameState.gameOver;
            redrawBoard(); // Redraw based on new state
            updateStatus(gameState.winner); // Update status based on new state
        });

        // Handle incoming chat messages
        socket.on('new_message', (data) => {
            console.log('New message received:', data);
            displayChatMessage(data.sender, data.text);
        });

        // Handle game errors from server
        socket.on('game_error', (message) => {
            console.error('Game Error:', message);
            // Display error temporarily in status, then revert? Or a dedicated error area?
            const oldStatus = statusElement.textContent;
            statusElement.textContent = `Error: ${message}`;
            // Revert status after a delay so player sees it
            setTimeout(() => {
                // Only revert if the status hasn't changed again (e.g. by game over)
                 if (statusElement.textContent === `Error: ${message}`) {
                    updateStatus(localGameOver ? (localBoard.includes(null) ? null : 'Draw') : null); // Update based on current known state
                 }
            }, 3000); // Show error for 3 seconds
        });

    } // End of setupSocketListeners

    // --- Add Click Listeners to Cells ---
    cells.forEach(cell => {
        cell.addEventListener('click', handleCellClick);
    });

    function handleCellClick(event) {
        // Check if connection exists
        if (!socket || !socket.connected) {
            console.log("Not connected to server.");
            return;
        }

        // Prevent moves if game over, not your turn, or cell filled
        if (localGameOver) return;
        if (localCurrentPlayer !== myPlayerSymbol) {
            console.log("Not your turn!");
            return;
        }

        const clickedCell = event.target;
        const cellIndex = parseInt(clickedCell.getAttribute('data-index'), 10);

        if (localBoard[cellIndex] !== null) {
            console.log('Cell already filled.');
            return;
        }

        console.log(`Sending 'make_move' event for index ${cellIndex}`);
        socket.emit('make_move', { index: cellIndex });
    }


    // --- Chat Functionality ---
    sendChatButton.addEventListener('click', sendChatMessage);
    chatInput.addEventListener('keypress', (event) => {
         if (event.key === 'Enter') {
             sendChatMessage();
         }
    });

    function sendChatMessage() {
        const messageText = chatInput.value.trim();
        if (messageText && socket && socket.connected) { // Check socket connection
            console.log('Sending chat message:', messageText);
            socket.emit('send_message', { text: messageText });
            chatInput.value = '';
        }
    }

    function displayChatMessage(sender, text) {
        const messageElement = document.createElement('p');
        const senderElement = document.createElement('strong');
        senderElement.textContent = `${sender}:`; // Backticks for consistency, though not strictly needed here
        messageElement.appendChild(senderElement);
        messageElement.appendChild(document.createTextNode(` ${text}`));
        chatMessages.appendChild(messageElement);
        chatMessages.scrollTop = chatMessages.scrollHeight; // Auto-scroll
    }


    // --- Redraw Board Function ---
    function redrawBoard() {
        cells.forEach((cell, index) => {
            const value = localBoard[index];
            cell.textContent = value ? value : '';
            cell.classList.remove('x', 'o');
            if (value) {
                cell.classList.add(value.toLowerCase());
            }
            // Update cursor based on cell state and game state
            if (value !== null || localGameOver || localCurrentPlayer !== myPlayerSymbol) {
                 cell.style.cursor = 'not-allowed';
             } else {
                 cell.style.cursor = 'pointer';
             }
        });
        console.log('Board redrawn.');
    }

    // --- Update Status Message Function ---
    function updateStatus(winner) { // Winner is passed from gameState in update_game handler
        if (localGameOver) {
            boardElement.style.pointerEvents = 'none'; // Disable board clicks visually
            if (winner === 'Draw') {
                statusElement.textContent = "Status: Game Over - It's a Draw!";
            } else if (winner) {
                 if (winner === myPlayerSymbol) {
                    statusElement.textContent = `Status: Game Over - You (${winner}) Win!`;
                 } else {
                     statusElement.textContent = `Status: Game Over - ${opponentName} (${winner}) Wins!`;
                 }
            } else {
                // This case might happen if opponent disconnects mid-game
                 statusElement.textContent = "Status: Game Over!";
            }
        } else {
            boardElement.style.pointerEvents = 'auto'; // Ensure board is clickable
            if (localCurrentPlayer === myPlayerSymbol) {
                 statusElement.textContent = `Status: Your Turn (${myPlayerSymbol})`;
             } else {
                 statusElement.textContent = `Status: ${opponentName}'s Turn (${localCurrentPlayer})`;
             }
        }
     }

}); // End of DOMContentLoaded listener