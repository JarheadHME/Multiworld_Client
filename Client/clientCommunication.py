"""
Handles Requests/Responses to the Back-end.
"""
import asyncio
import json
import websockets

from util.clientExceptions import ServerDisconnectWarning
from Client.clientGameConnection import ClientGameConnection

from PySide6.QtCore import Signal, QThread
from util.stompframemanager import StompFrameManager
from Model.itemDto import ItemDto
from Model.serverConfig import ServerConfig
from Model.setUpDto import SetUpDto
from Model.config import Config

from base_logger import logging
logger = logging.getLogger(__name__)

world_id: int = Config.get_config().get_world_id()
game_room: str = Config.get_config().get_game_room()
event_scanning: bool = Config.get_config().Scanner_Enabled
disable_multiplayer: bool = Config.get_config().Disable_Multiplayer
game_handler: ClientGameConnection = ClientGameConnection(world_id)

global gui_logger_signal
async def log(message: str) -> None:
    global gui_logger_signal
    if isinstance(gui_logger_signal, Signal):
        gui_logger_signal.emit(message)
    else:
        logger.info(message)


async def start_connections(server_config: ServerConfig, set_up_dto: SetUpDto, gui_logger_signal_source: Signal(str)) -> None:
    global gui_logger_signal
    gui_logger_signal = gui_logger_signal_source
    asyncio.create_task(game_handler.connect(gui_logger_signal))
    if not disable_multiplayer:
        await client(server_config)


async def client(server_config: ServerConfig) -> None:
    frame_manager = StompFrameManager(server_config)
    try:
        async with websockets.connect("ws://" + server_config.get_uri()) as client_websocket:
            await log(f"Attempting to Connect to {game_room}.........")
            await client_websocket.send(frame_manager.connect(server_config.server_ip))
            foo = await client_websocket.recv()
            if not foo.startswith("ERROR"):
                await client_websocket.send(frame_manager.subscribe(f"/topic/item/{game_room}"))
                asyncio.create_task(listen_to_server(client_websocket))
                await log(f"Successfully connected to the Server")
                while True:
                    for itemDto in game_handler.get_item_to_send():
                        await client_websocket.send(frame_manager.send_json(f"/app/item/{game_room}", json.dumps(itemDto.as_dict())))
                        game_handler.remove_item_to_send(itemDto)
                    if QThread.currentThread().isInterruptionRequested():
                        break
                    await asyncio.sleep(0)
                # Only gotten to once the loop is broken
                try:
                    await client_websocket.send(frame_manager.disconnect(""))
                    await client_websocket.close()
                    await log("Successfully disconnected from the Server")
                    QThread.currentThread().quit() # Tells thread to fully end
                except Exception as e:
                    await log(f"Error disconnecting from server:\n{e}")
                
            else:
                raise ServerDisconnectWarning()
    except ServerDisconnectWarning as sdw:
        await log("Failed to Subscribe to the Item Queue. Bad Server URL?")
    except Exception as e:
        await log("Problem with Server connection, please check the status with the Server host.")


async def listen_to_server(client_connection) -> None:
    async for message in client_connection:
        a = asyncio.create_task(handle_message(message))
        await asyncio.sleep(0)


async def handle_message(message) -> None:
    if message[:7] == "MESSAGE":
        contents = message.split("\n")
        item_dto = ItemDto.from_dict(json.loads(contents[-1][:-1]))
        if item_dto.sourcePlayerWorldId != world_id:
            game_handler.push_item_to_process(item_dto)

