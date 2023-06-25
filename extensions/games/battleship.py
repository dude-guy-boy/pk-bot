# battleship.py

import asyncio
from interactions import (
    Button,
    Client,
    Extension,
    Message,
    listen,
    slash_command,
    slash_option,
    SlashContext,
    OptionType,
    Embed,
    ButtonStyle,
    AutocompleteContext
    )
from interactions.api.events.internal import Component
import src.logs as logs
from lookups.colors import Color
from src.database import UserData
from random import randint, choice

class Battleship(Extension):
    def __init__(self, client: Client):
        self.client = client
        self.logger = logs.init_logger()

    ### /BATTLESHIP ###
    @slash_command(
        name="battleship",
        description="Play a game of battleship!",
    )
    async def play_battleship(self, ctx: SlashContext):
        game = BattleshipGame.get(ctx.author.id)

        # # If the user has an existing game, send it
        if game:
            # TODO: Retain the last embed message when its resent
            embed = Embed(description=f"{ctx.user.mention} here's your existing Battleship game!", color=Color.GREEN)

            # Check if the game was started
            if not game.started:
                embed.set_footer("Click on water to re-randomise, or on a ship to begin!")

            # Get and delete the old message
            old_message_channel = await ctx.guild.fetch_channel(game.message.channel)
            old_message = await old_message_channel.fetch_message(game.message.id)
            await old_message.delete()

            # Send the new message with the old board
            new_message = await ctx.send(embed=old_message.embeds[0], components=game.user.generate_buttons(started=game.started))

            # Save the new message
            game.set_message(new_message)
            game.save()

            return

        # Initialises a new battleship game
        if not game:
            game = BattleshipGame(ctx.author.id)

        # Send board
        buttons = game.user.generate_buttons(started=False)
        embed = Embed(description=f"{ctx.user.mention} here's your Battleship board!", footer="Click on water to re-randomise, or on a ship to begin!", color=Color.GREEN)
        msg = await ctx.send(embeds=embed, components=buttons)

        # Save game info
        game.set_message(msg)
        game.save()

    ### Battleship Button Listener ###
    @listen("on_component")
    async def battleship_listener(self, component: Component):
        # Ignore non battleship buttons
        if not component.ctx.custom_id.startswith("battleship"):
            return
        
        ctx = component.ctx
        custom_id = ctx.custom_id

        # Get battleship game
        game = BattleshipGame.get(ctx.author.id)

        # Check if button presser is the game owner
        if not game or game.message.id != str(ctx.message.id):
            await ctx.send(embeds=Embed(description="That isn't your battleship game!", color=Color.RED), ephemeral=True)
            
            if not game:
                UserData.delete_user(ctx.author.id)
            return

        # Get coordinate of button pressed
        coord = (int(custom_id[11:12]), int(custom_id[12:]))

        # Check if the game has started
        if not game.started:
            # If a ship was clicked, start the game
            if game.user.is_ship(coord):
                # Set started flag
                game.set_started(True)

                # If the bot should start
                if game.is_bots_turn:
                    # Say that pk bot is making the first move
                    starting_message: Message = await ctx.edit_origin(
                        embed=Embed(description=f"The game has now begun. {self.bot.user.mention} will make the first move.", color=Color.YORANGE),
                        components=game.user.generate_buttons(bots_turn=True, started=game.started)
                    )

                    # Wait a second to appear like its thinking
                    await asyncio.sleep(2)

                    # Make the move
                    valid_moves = game.user.get_all_valid_coords()
                    print(valid_moves)
                    move = choice(valid_moves)
                    print(move)

                    result = game.user.reveal(move)
                    buttons = game.user.generate_buttons(bots_turn=True, started=game.started)
                    await starting_message.edit(embeds=Embed(description=f"{game.get_move_string(result, coord, self.bot.user.mention)}", footer="Click anywhere to continue"), components=buttons)

                    game.set_turn(is_bots_turn=False)
                    game.save()
                    return

                # The user should start
                
                buttons = game.user.generate_buttons(bots_turn=False, started=game.started)
                game.save()

                await ctx.edit_origin(embed=Embed(description=f"The game has now begun. Please make the first move.", color=Color.GREEN), components=buttons)

                return
            
            # If they clicked water, regenerate their board
            game.regenerate_board()
            game.save()

            # Send regenerated board
            await ctx.edit_origin(components=game.user.generate_buttons(started=game.started))
            return

        # Check if its the users turn
        if game.is_bots_turn:
            # User clicked because prompt "Click anywhere to continue"
            # Say that pk bot is making its move
            game_message: Message = await ctx.edit_origin(
                embed=Embed(description=f"{self.bot.user.mention} is making their move.", color=Color.YORANGE),
                components=game.user.generate_buttons(bots_turn=True, started=game.started)
            )

            # Wait a second to appear like its thinking
            await asyncio.sleep(2)

            # Make the move
            valid_moves = game.user.get_all_valid_coords()
            print(valid_moves)
            move = choice(valid_moves)
            print(move)

            result = game.user.reveal(move)
            buttons = game.user.generate_buttons(bots_turn=True, started=game.started, latest_move=move)
            await game_message.edit(embeds=Embed(description=f"{game.get_move_string(result, coord, self.bot.user.mention)}", footer="Click anywhere to continue"), components=buttons)

            game.set_turn(is_bots_turn=False)
            game.save()
            return
        
        # Its the users turn

        # Check if they are "clicking to continue"

        if "footer" in ctx.message.embeds[0].__dict__ and "anywhere to continue" in ctx.message.embeds[0].footer.text:
            buttons = game.bot.generate_buttons(bots_turn=False, started=game.started)
            await ctx.edit_origin(embeds=Embed(description=f"Make your move!"), components=buttons)
            return

        # Reveal cell that they pressed
        result = game.bot.reveal(coord)
        buttons = game.bot.generate_buttons(bots_turn=False, started=game.started, latest_move=coord)
        await ctx.edit_origin(embeds=Embed(description=f"{game.get_move_string(result, coord, self.bot.user.mention)}\nClick anywhere to continue"), components=buttons)

        game.set_turn(is_bots_turn=True)
        game.bot.cycle_hits()
        game.save()

class BattleshipMessage:
    def __init__(self, message_id, channel_id) -> None:
        self.id = message_id
        self.channel = channel_id

class BattleshipGame:
    USER = 0
    BOT = 1

    def __init__(self, id, user = None, bot = None, started = None, is_bots_turn = None, message: BattleshipMessage = None) -> None:
        self.id = str(id)
        self.user = user if user else Board()
        self.bot = bot if bot else Board()
        self.started = started if started in (False, True) else False
        self.is_bots_turn = is_bots_turn if is_bots_turn in (False, True) else choice([True, False])
        self.message = message if message else None

    @classmethod
    # Gets a user by id
    def get(self, id):
        game = UserData.get_user(str(id))

        if not game:
            return None

        return BattleshipGame(
            id = str(id),
            user = Board(board = game['user']['board'], revealed = game['user']['revealed']),
            bot = Board(board = game['bot']['board'], revealed = game['bot']['revealed']),
            started = game['started'],
            is_bots_turn = game['is_bots_turn'],
            message = BattleshipMessage(game['message']['message_id'], game['message']['channel_id'])
        )

    # Gets the result of a move as a string
    def get_move_string(self, result, coord, bot_mention):
        who_did = bot_mention if self.is_bots_turn else "You"
        who_against = "your" if self.is_bots_turn else f"{bot_mention}'s"

        if result == Board.MISS:
            return f"{who_did} missed!"
        
        target_board = self.user if self.is_bots_turn else self.bot
        target_cell = Board.get(target_board, coord)
        ship_name = self.get_ship_name(target_cell)
        print(target_cell)
        print(ship_name)

        if result in (Board.HIT, Board.FRESH_HIT):
            return f"{who_did} hit {who_against} {ship_name} battleship!"
        
        if result == Board.SUNKEN_SHIP:
            return f"{who_did} sank {who_against} {ship_name} battleship!"
        
        return "???"

    # Returns ship name from input of its number
    def get_ship_name(self, ship):
        if ship == Board.SMALL_SHIP:
            return "small"
        
        if ship == Board.MEDIUM_SHIP:
            return "medium"
        
        if ship == Board.LARGE_SHIP:
            return "large"
        
        return "non-existant"

    # Resets the board
    def regenerate_board(self):
        self.user = Board()

    # Saves user data
    def save(self):
        if not self.message:
            raise(LookupError, "Battleship message was not set!")

        game = {
            "user": {
                "board": self.user.board,
                "revealed": self.user.revealed
            },
            "bot": {
                "board": self.bot.board,
                "revealed": self.bot.revealed
            },
            "started": self.started,
            "is_bots_turn": self.is_bots_turn,
            "message": {
                "message_id": str(self.message.id),
                "channel_id": str(self.message.channel)
            }
        }
        
        UserData.set_user(self.id, game)

    # Sets the board
    def set_board(self, board):
        self.user.board = board

    # Sets the bots board
    def set_bot_board(self, bot_board):
        self.bot.board = bot_board

    # Sets the started value
    def set_started(self, started: bool):
        self.started = started

    # Sets whos turn it is
    def set_turn(self, is_bots_turn: bool):
        self.is_bots_turn = is_bots_turn

    # Sets the revealed board
    def set_revealed(self, revealed):
        self.user.revealed = revealed

    # Sets the bots revealed board
    def set_bot_revealed(self, bot_revealed):
        self.bot.revealed = bot_revealed

    # Sets the battleship message
    def set_message(self, message: Message):
        self.message = BattleshipMessage(message_id=str(message.id), channel_id=str(message.channel.id))

class Board:
    WATER = 0
    SMALL_SHIP = 1
    MEDIUM_SHIP = 2
    LARGE_SHIP = 3

    NOTHING = 0
    MISS = 5
    HIT = 6
    FRESH_HIT = 7
    SUNKEN_SHIP = 8

    def __init__(self, board = None, revealed = None) -> None:
        self.board = board if board else self.generate_random_board()
        self.revealed = revealed if revealed else self.empty_board()

    # Gets a list of all valid coordinates
    def get_all_valid_coords(self):
        valid_coords = []
        for row in range(5):
            for col in range(5):
                if not self.is_revealed((row, col)):
                    valid_coords.append((row, col))

        return valid_coords

    # Reveals a cell
    def reveal(self, coord: tuple):
        # If the cell is a ship and has not been sunk mark it as a fresh hit

        # If a ship was hit
        if self.is_ship(coord):
            # Get ship type
            ship_type = self.get(coord)

            # Check if ship has been sunk
            ship_coordinates = self.get_ship_coordinates(ship_type)

            for coordinate in ship_coordinates:
                if coordinate == coord:
                    continue

                if not self.is_revealed(coordinate):
                    # Ship has not been sunk
                    self.revealed[coord[0]][coord[1]] = Board.FRESH_HIT
                    return Board.FRESH_HIT

            # Ship has been sunk
            for coordinate in ship_coordinates:
                self.revealed[coordinate[0]][coordinate[1]] = Board.SUNKEN_SHIP
            return Board.SUNKEN_SHIP
        
        self.revealed[coord[0]][coord[1]] = Board.MISS
        return Board.MISS

    # Changes all fresh hits into hits
    def cycle_hits(self):
        for row in range(5):
            for col in range(5):
                if self.revealed[row][col] == Board.FRESH_HIT:
                    self.revealed[row][col] = Board.HIT

    # Gets the contents of a cell
    def get(self, coord):
        return self.board[coord[0]][coord[1]]

    # Gets all coordinates of a ship
    def get_ship_coordinates(self, ship_type):
        coordinates = []
        for row in range(5):
            for col in range(5):
                if self.board[row][col] == ship_type:
                    coordinates.append((row, col))

        return coordinates

    # Checks if a cell has been revealed
    def is_revealed(self, coord: tuple):
        return self.revealed[coord[0]][coord[1]] != Board.NOTHING

    # Checks if the clicked cell is a ship
    def is_ship(self, coord: tuple):
        if self.board[coord[0]][coord[1]] in (Board.SMALL_SHIP, Board.MEDIUM_SHIP, Board.LARGE_SHIP):
            return True
        
        return False

    # Returns an empty 5x5 board
    def empty_board(self):
        return [[0] * 5 for _ in range(5)]

    # Reveals all cells adjacent to destroyed ships
    def reveal_adjacent_cells(self):
        for row in range(5):
            for col in range(5):
                if self.check_adjacent_to_destroyed_ship((row, col)):
                    self.reveal((row, col))

    # Checks if the cell is adjacent to a destroyed ship
    def check_adjacent_to_destroyed_ship(self, coord):
        row, col = coord
        offsets = [(-1, -1), (-1, 0), (-1, 1),
                (0, -1),           (0, 1),
                (1, -1), (1, 0), (1, 1)]

        for offset in offsets:
            new_row = row + offset[0]
            new_col = col + offset[1]
            if 0 <= new_row < 5 and 0 <= new_col < 5:
                if self.revealed[new_row][new_col] == Board.SUNKEN_SHIP:
                    return True
        
        return False

    # Returns the needed board
    def compose_board(self, bots_turn, started):
        if not started:
            # Return starting board type
            return self.board

        if bots_turn:
            # - Display user board
            # - Hits, misses and sunken ships should be displayed
            # TODO: this

            combined_boards = [[0] * 5 for _ in range(5)]  # Initialize a new 5x5 matrix with zeros

            for i in range(5):
                for j in range(5):
                    if self.revealed[i][j] != 0:  # Check if the value in matrix2 is non-zero
                        combined_boards[i][j] = self.revealed[i][j]
                    else:
                        combined_boards[i][j] = self.board[i][j]

            return combined_boards

        # It's the users turn
        # TODO: this
        return self.revealed

    # Generate buttons for minsweeper board
    def generate_buttons(self, bots_turn: bool = True, started: bool = True, latest_move: tuple = None):
        buttons = []

        # Reveal adjacent cells before generating buttons
        self.reveal_adjacent_cells()

        # Uses the bots revealed board if the users turn
        board = self.compose_board(bots_turn, started)
        print(board)
        
        # Set ship colour (green if game not started yet)
        ship_colour = ButtonStyle.GRAY if started else ButtonStyle.GREEN

        # Loop through all cells
        for row in range(5):
            row_buttons = []
            for col in range(5):
                # Get the cell from the correct board
                cell = board[row][col]
                latest_move = ButtonStyle.GREEN if (row, col) == latest_move else None

                # Set if button is disabled - True if users turn and cell has been revealed
                disabled = not bots_turn and self.is_revealed((row, col))

                # Miss
                # TODO: figure out how misses should be handled
                if cell == Board.MISS:
                    row_buttons.append(Button(style=latest_move if latest_move else ButtonStyle.GRAY, label="‎", custom_id=f"battleship_{row}{col}", disabled=True))
                    continue

                # Hit
                if cell == Board.HIT:
                    row_buttons.append(Button(style=latest_move if latest_move else ButtonStyle.GRAY, emoji="🔥", custom_id=f"battleship_{row}{col}", disabled=disabled))
                    continue

                # Fresh hit
                if cell == Board.FRESH_HIT:
                    row_buttons.append(Button(style=latest_move if latest_move else ButtonStyle.RED, emoji="💥", custom_id=f"battleship_{row}{col}", disabled=disabled))
                    continue

                # Sunken ship
                if cell == Board.SUNKEN_SHIP:
                    row_buttons.append(Button(style=latest_move if latest_move else ButtonStyle.RED, emoji="☠️", custom_id=f"battleship_{row}{col}", disabled=disabled))
                    continue

                # Small ship
                if cell == Board.SMALL_SHIP:
                    row_buttons.append(Button(style=latest_move if latest_move else ship_colour, emoji="⛵", custom_id=f"battleship_{row}{col}", disabled=disabled))
                    continue

                # Medium ship
                if cell == Board.MEDIUM_SHIP:
                    row_buttons.append(Button(style=latest_move if latest_move else ship_colour, emoji="🚢", custom_id=f"battleship_{row}{col}", disabled=disabled))
                    continue

                # Large ship
                if cell == Board.LARGE_SHIP:
                    row_buttons.append(Button(style=latest_move if latest_move else ship_colour, emoji="🛳️", custom_id=f"battleship_{row}{col}", disabled=disabled))
                    continue

                # Water
                if randint(1, 6) == 1:
                    row_buttons.append(Button(style=latest_move if latest_move else ButtonStyle.BLUE, emoji=choice(("🐳", "🐬", "🦭", "🐟", "🐠", "🐡", "🦈", "🐙", "🐚", "🐋", "🦑")), custom_id=f"battleship_{row}{col}", disabled=disabled))
                    continue

                row_buttons.append(Button(style=latest_move if latest_move else ButtonStyle.BLUE, label="‎", custom_id=f"battleship_{row}{col}", disabled=disabled))

            buttons.append(row_buttons)

        return buttons

    # Generates a board with random ship layout
    def generate_random_board(self):
        # Initialize board
        board = self.empty_board()

        # Define ship lengths
        ship_lengths = [3, 2, 1]

        # Place ships randomly on the board
        for length in ship_lengths:
            while True:
                # Randomly choose a starting position and orientation for the ship
                row = randint(0, 4)
                col = randint(0, 4)
                orientation = choice(['horizontal', 'vertical'])

                # Check if the ship fits in the chosen position and orientation
                if orientation == 'horizontal' and col + length <= 5:
                    valid = True
                    for i in range(length):
                        if not self.is_valid_ship_placement(row, col + i, board):
                            valid = False
                            break
                    if valid:
                        for i in range(length):
                            board[row][col + i] = length
                        break

                elif orientation == 'vertical' and row + length <= 5:
                    valid = True
                    for i in range(length):
                        if not self.is_valid_ship_placement(row + i, col, board):
                            valid = False
                            break
                    if valid:
                        for i in range(length):
                            board[row + i][col] = length
                        break

        return board

    # Checks if a position is valid for ship placement
    def is_valid_ship_placement(self, row, col, board):
        # Check if the position is out of bounds
        if row < 0 or row >= 5 or col < 0 or col >= 5:
            return False

        # Check if the position or its adjacent positions already have a ship
        for r in range(row - 1, row + 2):
            for c in range(col - 1, col + 2):
                if r >= 0 and r < 5 and c >= 0 and c < 5 and board[r][c] != 0:
                    return False

        return True

    # Based on the cell location returns the offsets from it that within the board
    def compute_checkable_offsets(self, cell_coordinate):
        offsets = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]

        # Remove impossible offsets
        if cell_coordinate[0] == 0:
            # Cant check cells above
            remove_offsets = [(-1, -1), (-1, 0), (-1, 1)]
            for offset in remove_offsets:
                try:
                    offsets.remove(offset)
                except:
                    pass

        if cell_coordinate[0] == 4:
            # Cant check cells below
            remove_offsets = [(1, -1), (1, 0), (1, 1)]
            for offset in remove_offsets:
                try:
                    offsets.remove(offset)
                except:
                    pass

        if cell_coordinate[1] == 0:
            # Cant check cells to the left
            remove_offsets = [(-1, -1), (0, -1), (1, -1)]
            for offset in remove_offsets:
                try:
                    offsets.remove(offset)
                except:
                    pass

        if cell_coordinate[1] == 4:
            # Cant check cells to the right
            remove_offsets = [(-1, 1), (0, 1), (1, 1)]
            for offset in remove_offsets:
                try:
                    offsets.remove(offset)
                except:
                    pass
        
        return offsets

def setup(bot):
    # This is called by interactions.py so it knows how to load the Extension
    Battleship(bot)