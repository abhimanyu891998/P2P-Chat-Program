#!/usr/bin/python3

# Development platform: Mac OS
# Python version: 3.7
# Version: 1.0


from tkinter import *
import sys
import socket
from threading import Thread, Event
import select

#
# Global variables
#

USERNAME = None
CURRENT_CHATROOM = None
CONNECTED_ROOM = None
SERVER_ADDRESS = None
SERVER_PORT = None
CHAT_PORT = None
CHAT_IP = None
ROOM_LIST_SOCKET = None
ROOM_SERVER_CHAT_SOCKET = None
END_MESSAGE_STRING = "::\r\n"
KEEP_ALIVE_THREAD = None
BACKWARD_THREAD = None
BACKWARD_LINK_ARRAY = {}
BACKWARD_SOCKET = None
POKE_THREAD = None
POKE_SOCKET = None
MEMBER_LIST = None
FORWARD_LINK_THREAD = None
CURRENT_USER = None
CURRENT_USER_HASH = None
FORWARD_LINK_SOCKET = None
PEER_LATEST_MESSAGE_ID = {}
MESSAGE_ID = 0
MESSAGE_LISTENER_THREAD = None


# ---self-defined classes --- #


"""
A model list to store the latest members in a chatroom
"""
class MemberList:
    member_list = []
    hash_value = None


"""
a model class to store the user details
"""

class User:
    hashID = ""

    def __init__(self, username, ip, port, hash):
        self.username = username
        self.ip = ip
        self.port = port
        self.hashID = hash

    def __str__(self):
        return self.hashID + " " + self.username

    def __repr__(self):
        return '(' + self.hashID + ":" + self.username + self.port + ')'



"""
A thread class to listen continuously for messages
"""
class MessageListener(Thread):
    def __init__(self, thread_id, thread_name):
        Thread.__init__(self)
        self.id = thread_id
        self.name = thread_name
        self.event = Event()

    def run(self):
        global FORWARD_LINK_THREAD, FORWARD_LINK_SOCKET, BACKWARD_LINK_ARRAY, MEMBER_LIST
        while True:
            if self.event.wait(0.3):
                print("Self event wait for message listener")
                return
            else:
                list_of_sockets_to_listen_to = get_all_sockets()
                try:
                    reading_sockets, _, _ = select.select(list_of_sockets_to_listen_to, [], [], 2)
                except Exception as emsg:
                    print('Select threw an exception '+str(emsg))
                for sock in reading_sockets:
                        message = receive_message_text_listener(sock)
                        if message == "":
                            # empty message
                            continue
                        elif not message:
                            #remove the peer who left
                            if sock == FORWARD_LINK_SOCKET:
                                FORWARD_LINK_THREAD.join()
                                FORWARD_LINK_SOCKET = None
                                FORWARD_LINK_THREAD = ForwardLinkThread(1, 'connectToPeersThread')
                                FORWARD_LINK_THREAD.start()
                            for key in BACKWARD_LINK_ARRAY.keys():
                                if BACKWARD_LINK_ARRAY[key] == sock:
                                    sock_close = BACKWARD_LINK_ARRAY.pop(key)
                                    sock_close.close()
                                    break
                            continue
                        if text_message_validity(message):
                            contents = message.strip('{T:|::\r\n}').split(':')
                            peername = contents[2]
                            roomname, originHID, origin_username = contents[0:3]
                            message_id, msgLength = contents[3:5]
                            # message might contain :
                            message_data = ':'.join(contents[5:])
                            list_of_username = []
                            for member in MEMBER_LIST.member_list:
                                list_of_username.append(member.username)

                            if origin_username not in list_of_username:
                                print('Message from unknown peer,' +
                                      'sending join request.')
                                join_req = get_join_request(CURRENT_CHATROOM)
                                status = send_tcp_request(ROOM_SERVER_CHAT_SOCKET, join_req)
                                if not status:
                                    insert_message_in_command_window("[Join_Error] Server rejected request")
                                    return
                                r_msg, success = receive_message(ROOM_SERVER_CHAT_SOCKET)
                                if success:
                                    if is_valid_response_for_join(r_msg):
                                        print("Calling update member list from backward listener ")
                                        parse_response_for_join(r_msg)
                            # add message_id to seen ones
                            if update_message_ids(message_id, peername):
                                # we haven't seen this message before
                                # forward to all connections
                                print('Have not seen this message yet.')
                                recipients = get_recipients(origin_username, sock)
                                send_message_to_connected_sockets(message, recipients)
                                insert_message_in_message_window(origin_username + ':' + message_data)



"""
A thread to send request to server for keeping alvie the connection every 20 seconds.
"""

class KeepAlive(Thread):
    tag = "[Thread: KEEP_ALIVE]"

    def __init__(self, thread_id, thread_name):
        Thread.__init__(self)
        self.id = thread_id
        self.name = thread_name
        self.event = Event()

    def run(self):
        global ROOM_SERVER_CHAT_SOCKET, CURRENT_CHATROOM
        if not ROOM_SERVER_CHAT_SOCKET:
            print(self.tag + "Room server not connected, re-initiating connection now")
            sock = connect_to_room_server()
            if not sock:
                print(self.tag + " failed to connect with the sever")
                return
            else:
                ROOM_SERVER_CHAT_SOCKET = sock
                print(self.tag + " connected to server")
        while True:
            if self.event.wait(20):
                return
            else:
                reinit_join_req = get_join_request(CURRENT_CHATROOM)
                status = send_tcp_request(ROOM_SERVER_CHAT_SOCKET, reinit_join_req)
                if not status:
                    insert_message_in_command_window("[Join_Error] Server rejected request")
                    return
                r_msg, success = receive_message(ROOM_SERVER_CHAT_SOCKET)
                if success:

                    parse_response_for_join(r_msg)
                else:
                    insert_message_in_command_window("[Join_Error]: Client connection is broken")

"""
A thread to listen to pokes and manage ui accordingly
"""
class PokeThread(Thread):

    def __init__(self, thread_id, thread_name):
        Thread.__init__(self)
        self.id = thread_id
        self.name = thread_name
        self.event = Event()

    def run(self):
        global POKE_SOCKET
        if not POKE_SOCKET:
            success = create_poke_socket()
            POKE_SOCKET.settimeout(2)
            if not success:
                print('[Poke_thread_error] Poke thread setup error')
                return

        while True:
            try:
                response, sender = POKE_SOCKET.recvfrom(1000)
                response = response.decode('ascii')
            except socket.timeout as e:
                if self.event.is_set():
                    return
                continue
            except Exception as emsg:
                print('[Poke_thread_error] Error receiving poke')
                return

            success = parse_poke_message(response)

            if success:
                try:
                    print('sender is', sender)
                    POKE_SOCKET.sendto(bytes('A::\r\n', 'ascii'), sender)

                except Exception as emsg:
                    print('[Poke_thread_error] Error sending response to poke sender')


"""
A thread to listne to backward peer connections
"""
class BackwardThreadListener(Thread):
    def __init__(self, thread_id, thread_name):
        Thread.__init__(self)
        self.id = thread_id
        self.name = thread_name
        self.event = Event()

    def run(self):
        global BACKWARD_SOCKET
        global BACKWARD_LINK_ARRAY
        global CHAT_PORT
        global MESSAGE_LISTENER_THREAD
        global MEMBER_LIST
        if not BACKWARD_SOCKET:
            BACKWARD_SOCKET = socket.socket()
            BACKWARD_SOCKET = bind_socket_to_port(BACKWARD_SOCKET, CHAT_PORT)

        if BACKWARD_SOCKET:
            BACKWARD_SOCKET.settimeout(1)
            while True:

                try:
                    BACKWARD_SOCKET.listen(1)
                    sock, address = BACKWARD_SOCKET.accept()
                except socket.timeout as e:
                    if self.event.is_set():
                        return
                    continue
                except Exception as emsg:
                    print('Error accepting messages on backward link. ' + emsg)
                    return

                response, success = receive_message(sock)
                print("backward link response is", response)

                # ------To Update member list-----#
                if success:
                    join_req = get_join_request(CURRENT_CHATROOM)
                    status = send_tcp_request(ROOM_SERVER_CHAT_SOCKET, join_req)
                    if not status:
                        insert_message_in_command_window("[Join_Error] Server rejected request")
                        return
                    r_msg, success = receive_message(ROOM_SERVER_CHAT_SOCKET)
                    if success:
                        if is_valid_response_for_join(r_msg):
                            print("Calling update member list from backward listener ")
                            parse_response_for_join(r_msg)
                    # -------------------------------------------------------#

                    if response.startswith('P:') and response.endswith(':\r\n'):
                        message = response.strip('{P:|::\r\n}').split(':')
                        name_of_peer = message[1]
                        message_id = message[4]
                        flag_found = False

                        for member in MEMBER_LIST.member_list:
                            if name_of_peer == member.username:
                                flag_found = True
                                response_to_peer = ('S:' + str(message_id) + '::\r\n')
                                success = send_tcp_request(sock, response_to_peer)
                                if not success:
                                    print('Could not send response for peer request')

                                else:
                                    BACKWARD_LINK_ARRAY[member.hashID] = sock

                                    # updating message id
                                    update_message_ids(message_id, name_of_peer)
                                    insert_message_in_command_window(
                                        "Established a backward link with port " + member.port)
                                    # textThread() start
                                    if not MESSAGE_LISTENER_THREAD:
                                        MESSAGE_LISTENER_THREAD = MessageListener(4, 'message_listener')
                                        MESSAGE_LISTENER_THREAD.start()

                        if not flag_found:
                            insert_message_in_command_window("The backward link request is not from a valid peer")
                            sock.close()
                    else:
                        sock.close()
                else:
                    print("Could not receive a response from peer")
                    sock.close()

"""
A thread to connect a forward link  of the current peer
"""
class ForwardLinkThread(Thread):
    def __init__(self, thread_id, thread_name):
        Thread.__init__(self)
        self.id = thread_id
        self.name = thread_name
        self.event = Event()

    def run(self):
        perform_forward_linking(self)



""" a function to perform the final forward linking, called every two seconds"""
def perform_forward_linking(thread):
    print("Forward Link thread started")
    global MEMBER_LIST, CHAT_PORT, CHAT_IP, CURRENT_USER, BACKWARD_LINK_ARRAY, CURRENT_USER_HASH, FORWARD_LINK_SOCKET, CURRENT_CHATROOM, END_MESSAGE_STRING, MESSAGE_ID
    global MESSAGE_LISTENER_THREAD
    chat_user_index = None
    print("list at forward link thread is " + str(MEMBER_LIST.member_list))
    for index in range(len(MEMBER_LIST.member_list)):
        if MEMBER_LIST.member_list[index].hashID == CURRENT_USER.hashID:
            chat_user_index = index
            break
    start = (chat_user_index + 1) % len(MEMBER_LIST.member_list)
    while CURRENT_USER_HASH != MEMBER_LIST.member_list[start].hashID and len(MEMBER_LIST.member_list) > 1:
        if MEMBER_LIST.member_list[start].hashID in BACKWARD_LINK_ARRAY.keys():
            # already have established a backward link with this user
            start = (start + 1) % len(MEMBER_LIST.member_list)
        else:
            # connect to forward link
            FORWARD_LINK_SOCKET = socket.socket()
            forward_link_ip = MEMBER_LIST.member_list[start].ip
            forward_link_port = MEMBER_LIST.member_list[start].port
            FORWARD_LINK_SOCKET = connect_socket_to_server(FORWARD_LINK_SOCKET, forward_link_ip, forward_link_port)
            if FORWARD_LINK_SOCKET:
                request = ('P:' + CURRENT_CHATROOM + ':' + USERNAME +
                           ':' + CHAT_IP + ':' + CHAT_PORT +
                           ':' + str(MESSAGE_ID) + '::\r\n')

                result = send_tcp_request(FORWARD_LINK_SOCKET, request)
                if result:
                    response, success = receive_message(FORWARD_LINK_SOCKET)
                    if success:
                        if response.startswith('S:') and response.endswith(END_MESSAGE_STRING):
                            print("Response received from peer and forward linking established" + str(
                                FORWARD_LINK_SOCKET))
                            insert_message_in_command_window(
                                "Forward link established with " + MEMBER_LIST.member_list[start].port)
                            message_id = response.strip('S: | ::\r\n')
                            username_of_peer = MEMBER_LIST.member_list[start].username
                            update_message_ids(message_id, username_of_peer)

                            # start text message listener
                            if not MESSAGE_LISTENER_THREAD:
                                MESSAGE_LISTENER_THREAD = MessageListener(4, 'message_listener')
                                MESSAGE_LISTENER_THREAD.start()
                            break
                        else:
                            print("Was not able to receive a valid response from other peer" + str(response))
                            FORWARD_LINK_SOCKET = None
                            start = (start + 1) % len(MEMBER_LIST.member_list)
                    else:
                        start = (start + 1) % len(MEMBER_LIST.member_list)
            else:
                start = (start + 1) % len(MEMBER_LIST.member_list)
    if not FORWARD_LINK_SOCKET:
        # could not connect to any peer
        print("No current connection, will try resetablishing in 2 seconds again")
        if thread.event.wait(2):
            return
        perform_forward_linking(thread)


# ------------*******-----------------#
# --------Self defined Functions------#

# ----signal handler -----#


def get_arguments_from_sys():
    global SERVER_ADDRESS, SERVER_PORT, CHAT_PORT
    SERVER_ADDRESS = sys.argv[1]
    SERVER_PORT = sys.argv[2]
    CHAT_PORT = sys.argv[3]


def receive_message_text_listener(sock):
    """receiving message on a socket"""
    try:
        response = sock.recv(1000).decode('ascii')
    except Exception as e:
        return False
    return response


def text_message_validity(message):
    """check whether message response follows protocol"""
    if not (message.startswith('T:') and message.endswith('::\r\n')):
        print('Received invalid text message.')
        return False
        # extract fields in message
    message_components = message.strip('{T:|::\r\n}').split(':')
    chat_room, originHID, origin_username = message_components[0:3]
    message_id, message_length = message_components[3:5]

    # if message came  from my chatroom
    global CURRENT_CHATROOM
    if chat_room != CURRENT_CHATROOM:
        print('[Received message from invalid chatroom')
        return False

    global USERNAME
    if origin_username == USERNAME:
        print('Own message received, discarding')
        return False

    return True


def update_message_ids(messageID, nameOfPeer):
    """update message ids according to incoming message ids"""
    global PEER_LATEST_MESSAGE_ID
    if nameOfPeer not in PEER_LATEST_MESSAGE_ID.keys():
        PEER_LATEST_MESSAGE_ID[nameOfPeer] = int(messageID)
        return True
    elif int(messageID) > PEER_LATEST_MESSAGE_ID[nameOfPeer]:
        PEER_LATEST_MESSAGE_ID[nameOfPeer] = int(messageID)
        return True

    else:
        return False


def connect_to_room_server():
    """connect to room server's port"""
    global SERVER_PORT, SERVER_ADDRESS
    success, sock = tcp_connect(SERVER_ADDRESS, SERVER_PORT)
    if success:
        return sock
    else:
        return None


def get_recipients(message_sender, socket):
    """gives you the recipients excluding you and your sender"""
    global MEMBER_LIST
    sockets = set(get_all_sockets())
    sockets.discard(socket)
    message_sender_hash_id = None
    for member in MEMBER_LIST.member_list:
        if member.username == message_sender:
            message_sender_hash_id = member.hashID

    global BACKWARD_LINK_ARRAY
    print("Member hash id "+str(message_sender_hash_id))
    for hashID in BACKWARD_LINK_ARRAY.keys():
        if hashID == message_sender_hash_id:
            sockets.discard(BACKWARD_LINK_ARRAY[hashID])
    return sockets
    # Returns sockets except sender and receiver

def print_member_list():
    """puts the members list into comnmand window on join request"""
    global MEMBER_LIST
    string_to_print = ""
    for member in MEMBER_LIST.member_list:
        string_to_print+= member.username+" "+member.ip+" "+member.port+"\n"
    return string_to_print

def get_all_sockets():
    """retyurn all sockets in forward link and backward link array """
    global FORWARD_LINK_SOCKET, BACKWARD_LINK_ARRAY
    links = []
    if FORWARD_LINK_SOCKET:
        links.append(FORWARD_LINK_SOCKET)

    for key in BACKWARD_LINK_ARRAY.keys():
        links.append(BACKWARD_LINK_ARRAY[key])
        # print("Links are " + str(links))
    return links


def bind_socket_to_port(sock, port):
    global CHAT_IP
    try:
        sock.bind((CHAT_IP, int(port)))
    except Exception as emsg:
        sock.close()
        print('Socket bind error' + str(emsg))
        return None
    return sock


def connnect_socket_to_port(sock, ip, port):
    try:
        sock.connect((ip, port))
    except Exception as e:
        sock.close()
        return None
    return sock


def create_poke_socket():
    """create a poke socket for udp connection"""
    global CHAT_PORT, POKE_SOCKET
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock = bind_socket_to_port(sock, CHAT_PORT)
    if sock:
        POKE_SOCKET = sock
        print('Poke socket created')
    else:
        print('Poke socket could not be created')
        return False
    return True


# function to establish TCP connection, return a socket object sock
def tcp_connect(ip, port):
    """Connect a tcp connection at ip and port"""
    try:
        sock = socket.socket()
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.connect((ip, int(port)))
    except socket.error as emsg:
        print("Socket connect error:", emsg)
        return False, emsg
        # sys.exit(1)
    return True, sock


# function to establish UDP connection, returns a socket object sock
def udp_connect():
    """ connect a udp connection"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    except socket.error as emsg:
        print('Error creating udp socket')
        return False, emsg

    return True, sock


def is_valid_update_of_username(username):
    """checks whether user can update his username"""
    # case occurs when user has already joined a chat room
    if CURRENT_CHATROOM:
        insert_message_in_command_window('[Username_Error] Chat_Room is already joined')
        return False
    # invalid username, in this case empty
    if not username:
        insert_message_in_command_window('[Username_Error] Username cannot be empty')
        return False
    # if username contains ':'
    if username.find(':') > -1:
        insert_message_in_command_window('[Username_Error] Username contains :')
        return False
    return True


def is_valid_join_request(chatroom_to_join):
    """check whether the join requewst is valid or not"""
    global USERNAME, CURRENT_CHATROOM
    # case occurs when user has already joined a chat room
    if not USERNAME:
        insert_message_in_command_window('[Join_Error] Must have a username defined first')
        return False
    # invalid username, in this case empty
    if not chatroom_to_join:
        insert_message_in_command_window('[Join_Error] Provide the chatroom name you want to join')
        return False
    # if username contains ':'
    if CURRENT_CHATROOM:
        insert_message_in_command_window('[Join_Error] Chatroom already joined:')
        return False
    return True


def terminate_forward_thread_and_restart():
    global FORWARD_LINK_SOCKET, FORWARD_LINK_THREAD
    FORWARD_LINK_THREAD.join()
    FORWARD_LINK_THREAD = ForwardLinkThread(1, 'FORWARD_LINK_THREAD')
    FORWARD_LINK_SOCKET = None
    FORWARD_LINK_THREAD.start()


def close_backward_socket(key):
    global BACKWARD_LINK_ARRAY
    socket_to_close = BACKWARD_LINK_ARRAY.pop(key)
    socket_to_close.close()


def send_message_to_connected_sockets(message_to_send, sockets):
    global FORWARD_LINK_SOCKET, FORWARD_LINK_THREAD, BACKWARD_LINK_ARRAY
    print('[DEBUG] Attempting to send message: ' + message_to_send
          + ' to ' + str(sockets))
    print("At this point backward link array is "+str(BACKWARD_LINK_ARRAY))
    while sockets:
        _, write_sockets, _ = select.select([], sockets, [], 2)
        for sock in write_sockets:
            sockets.remove(sock)
            success = send_tcp_request(sock, message_to_send)
            if not success:
                if FORWARD_LINK_SOCKET == sock:
                    terminate_forward_thread_and_restart()
                for hashID in BACKWARD_LINK_ARRAY.keys():
                    if BACKWARD_LINK_ARRAY[hashID] == sock:
                        close_backward_socket(hashID)
                        break
            else:
                print("Message sent to socket " + str(sock))
    print('[DEBUG] Message sent.')
    return


def get_poke_user_details(user_to_poke):
    global CURRENT_CHATROOM, MEMBER_LIST

    # if user isn't in a chatroom
    if not CURRENT_CHATROOM:
        insert_message_in_command_window('[Poke_Error] You are not in a chatroom yet')
        return None
    # if no user has been mentioned to poke
    if not user_to_poke:
        members = ''
        if MEMBER_LIST:
            for member in MEMBER_LIST.member_list:
                members = members + member.username + '\n'
        insert_message_in_command_window('To whom do you want to poke?\nThe members in this ChatRoom are\n' + members)
        return None

    # if the user tries to poke self
    if user_to_poke == USERNAME:
        insert_message_in_command_window('[Poke_Error] You can\'t poke yourself')
        return None

    # MEMBER_DETAILS PARSING WILL COME HERE
    for member in MEMBER_LIST.member_list:
        if user_to_poke == member.username:
            return (member)

    members = ''
    if MEMBER_LIST:
        for member in MEMBER_LIST.member_list:
            members = members + member.username + '\n'
    insert_message_in_command_window(
        '[Poke_Error] This nickname is not in this Chatroom\nThe members in this ChatRoom are\n' + members)


def send_tcp_request(socket, request):
    try:
        socket.send(bytes(request, 'ascii'))
        return True
    except Exception as e:
        return False


def send_udp_request(socket, request, user):
    try:
        socket.sendto(bytes(request, 'ascii'), (user.ip, int(user.port)))
        return True
    except Exception as emsg:
        print("udp error is", emsg)
        return False


def insert_message_in_command_window(message):
    CmdWin.insert(1.0, "\n" + message)

def insert_message_in_message_window(message):
    MsgWin.insert(1.0, "\n" + message)


def connect_socket_to_server(socket_object, server_address, server_port):
    try:
        socket_object.connect((server_address, int(server_port)))
        return socket_object
    except Exception as e:
        socket_object.close()
        print('[SOCKET_ERROR] Error creating a socket ' + str(e))
        return None


def receive_message(sock):
    try:
        response = sock.recv(1000).decode('ascii')
        return response, True
    except:
        print('[ERROR] Did not receive anything in request')
        return None, False


def receive_udp_message(sock):
    try:
        response = sock.recvfrom(1000).decode('ascii')
        return response, True
    except:
        print("[ERROR] Did not receive anything in request")
        return None, False


def get_join_request(chat_room):
    global USERNAME, ROOM_SERVER_CHAT_SOCKET, END_MESSAGE_STRING, CHAT_IP, CURRENT_USER, CURRENT_USER_HASH
    CHAT_IP = ROOM_SERVER_CHAT_SOCKET.getsockname()[0]
    string_to_gen_hash = str(USERNAME) + str(CHAT_IP) + str(CHAT_PORT)
    hash_gen = sdbm_hash(string_to_gen_hash)
    CURRENT_USER = User(USERNAME, CHAT_IP, CHAT_PORT, str(hash_gen))
    CURRENT_USER_HASH = CURRENT_USER.hashID
    request = 'J:' + chat_room + ':' + USERNAME + ":" + str(CHAT_IP) + ":" + str(CHAT_PORT) + END_MESSAGE_STRING
    return request


def parse_list_of_chatrooms_from_response(response):
    if response.startswith('G') and response.endswith('::\r\n'):
        edited_string = response.strip('G')
        edited_string = edited_string.strip('::\r\n')
        if len(edited_string) > 0:
            # this means we have names
            chatroom_names = edited_string.split(':')
            return chatroom_names
        else:
            return "No chatrooms to be displayed"
    elif response.startswith('F') and response.endswith('::\r\n'):
        return "Error retrieving chat room list: " + response.strip("F: | ::\r\n")


def is_valid_response_for_join(response):
    if response.startswith('M:') and response.endswith(str(END_MESSAGE_STRING)):
        meaningful_response = response.strip('M: | ::\r\n').split(':')
        return True, meaningful_response
    elif response.startswith('F:') and response.endswith(str(END_MESSAGE_STRING)):
        error_message = response.strip('F: | ::\r\n')
        return False, error_message
    else:
        return False, "Server responded with a different protocol, Cannot parse"


def parse_response_for_join(response):
    global END_MESSAGE_STRING
    success, result = is_valid_response_for_join(response)

    if success:
        update_member_list(result)
    else:
        insert_message_in_command_window("[JOIN_ERROR]: " + result)


def extract_member_list(unedited_list):
    global MEMBER_LIST
    MEMBER_LIST.member_list = []
    index = 0
    while index <= len(unedited_list) - 2:
        username = unedited_list[index]
        ip = unedited_list[index + 1]
        port = unedited_list[index + 2]
        string_to_gen_hash = str(username) + str(ip) + str(port)
        hash_gen = sdbm_hash(string_to_gen_hash)
        user_to_add = User(username, ip, port, str(hash_gen))
        MEMBER_LIST.member_list.append(user_to_add)
        # print("New member list :" + str(MEMBER_LIST.member_list))
        index = index + 3


def get_message_request(text_to_send):
    global CURRENT_CHATROOM, USERNAME, MEMBER_LIST, MESSAGE_ID, CURRENT_USER_HASH, END_MESSAGE_STRING
    request = 'T:' + CURRENT_CHATROOM + ':'
    request += CURRENT_USER_HASH + ':' + USERNAME + ':' + str(MESSAGE_ID) + ':' + str(
        len(text_to_send)) + ':' + text_to_send + END_MESSAGE_STRING
    MESSAGE_ID += 1
    return request


def update_member_list(unedited_list):
    global MEMBER_LIST
    new_hash = unedited_list[0]
    if not MEMBER_LIST:
        MEMBER_LIST = MemberList()
    if not MEMBER_LIST.hash_value:
        MEMBER_LIST.hash_value = new_hash
        unedited_list.pop(0)
        extract_member_list(unedited_list)
    else:
        if MEMBER_LIST.hash_value != new_hash:
            MEMBER_LIST.hash_value = new_hash
            unedited_list.pop(0)
            extract_member_list(unedited_list)



def parse_poke_message(response):
    if response.startswith('K:') and response.endswith(':\r\n'):
        response = response.strip('{K:|::\r\n}').split(':')
        poke_username, poke_roomname = response[1], response[0]
        insert_message_in_command_window('You were poked by ' + poke_username + ' from the chatroom ' + poke_roomname)

    else:
        print('Invalid UDP Message received')
        return False

    return True


# ------end of self-defined functions---------#
#
# This is the hash function for generating a unique
# Hash ID for each peer.
# Source: http://www.cse.yorku.ca/~oz/hash.html
#
# Concatenate the peer's username, str(IP address), 
# and str(Port) to form a string that be the input 
# to this hash function
def sdbm_hash(instr):
    hash = 0
    for c in instr:
        hash = int(ord(c)) + (hash << 6) + (hash << 16) - hash
    return hash & 0xffffffffffffffff


#
# Functions to handle user input
#

def do_User():
    global USERNAME
    input_username = userentry.get()
    # Here, we need to check if the user request is valid.
    # For this we use the function is_valid_update_of_username()
    if is_valid_update_of_username(input_username):
        # update username
        USERNAME = input_username
        # display successful message
        print('Successfully changed username to: %s' % USERNAME)
        logging_message = "[User] username: " + USERNAME
        insert_message_in_command_window(logging_message)
        # clear user input
        userentry.delete(0, END)


def do_List():
    global SERVER_ADDRESS, SERVER_PORT, ROOM_SERVER_CHAT_SOCKET

    if not ROOM_SERVER_CHAT_SOCKET:
        # connect to server
        sock = connect_to_room_server()
        # check if connection is successful
        if not sock:
            insert_message_in_command_window("[List_Error]: Failed to connect to server to process request")
            return
        else:
            ROOM_SERVER_CHAT_SOCKET = sock
            print("[List] connected to server")

    # this part will only execute if the socket is connected
    request = "L" + END_MESSAGE_STRING
    status = send_tcp_request(ROOM_SERVER_CHAT_SOCKET, request)

    if not status:
        insert_message_in_command_window("[List_Error] Server rejected request")
        return
    # receive response from room server
    r_msg, success = receive_message(ROOM_SERVER_CHAT_SOCKET)
    # check if successfully receive response from room server
    if success:
        # list received now need to parse it
        response = parse_list_of_chatrooms_from_response(r_msg)
        insert_message_in_command_window("[Chat_Rooms_List]: " + str(response))
    else:
        insert_message_in_command_window("[List_Error]: Client connection is broken")


def do_Join():
    global ROOM_SERVER_CHAT_SOCKET, CURRENT_CHATROOM, KEEP_ALIVE_THREAD, POKE_THREAD, MEMBER_LIST, BACKWARD_THREAD, FORWARD_LINK_THREAD
    chatroom_name_to_join = userentry.get()
    if is_valid_join_request(chatroom_name_to_join):

        # check if socket is established
        if not ROOM_SERVER_CHAT_SOCKET:
            # i not establish a tcp connection
            sock = connect_to_room_server()
            # check if connection is successful
            if not sock:
                insert_message_in_command_window("[Join_Error]: Failed to connect to server to process request")
                return
            else:
                ROOM_SERVER_CHAT_SOCKET = sock
                print("[Join] connected to server")

        join_req = get_join_request(chatroom_name_to_join)
        status = send_tcp_request(ROOM_SERVER_CHAT_SOCKET, join_req)
        if not status:
            insert_message_in_command_window("[Join_Error] Server rejected request")
            return
        r_msg, success = receive_message(ROOM_SERVER_CHAT_SOCKET)
        if success:
            if is_valid_response_for_join(r_msg):
                CURRENT_CHATROOM = chatroom_name_to_join
                parse_response_for_join(r_msg)
                if len(MEMBER_LIST.member_list) > 0:
                    insert_message_in_command_window('[Join]: Joined a chatroom ' + str(CURRENT_CHATROOM))
                    string_to_print = "Members in this chat room are : \n"
                    string_to_print+= print_member_list()
                    insert_message_in_command_window(string_to_print)
                    KEEP_ALIVE_THREAD = KeepAlive(1, 'KEEP_ALIVE')
                    KEEP_ALIVE_THREAD.start()
                    POKE_THREAD = PokeThread(2, 'POKE_THREAD')
                    POKE_THREAD.start()
                    FORWARD_LINK_THREAD = ForwardLinkThread(3, 'FORWARD_LINK_THREAD')
                    FORWARD_LINK_THREAD.start()
                    BACKWARD_THREAD = BackwardThreadListener(4, 'BACKWARD_LINK_THREAD')
                    BACKWARD_THREAD.start()


                else:
                    print("Some problem with parsing member list")

        else:
            insert_message_in_command_window("[Join_Error]: Client connection is broken")
    else:
        print("Some error check command window")

    userentry.delete(0, END)


def do_Send():
    global MESSAGE_ID, USERNAME, FORWARD_LINK_SOCKET, BACKWARD_LINK_ARRAY, CURRENT_CHATROOM
    MESSAGE_ID += 1

    text = userentry.get()
    userentry.delete(0, END)
    if text == "":
        insert_message_in_command_window("Cannot send empty message")
    else:
        message = get_message_request(text)
        if CURRENT_CHATROOM:
            if len(BACKWARD_LINK_ARRAY) > 0 or FORWARD_LINK_SOCKET:
                send_message_to_connected_sockets(message, get_all_sockets())
        insert_message_in_message_window(USERNAME + ":" + text)


def do_Poke():
    user_to_poke = userentry.get()
    user_to_send = get_poke_user_details(user_to_poke)
    if user_to_send:
        success, sock = udp_connect()
        if success:
            recepient_socket = sock
        else:
            print("[UDP_ERROR] Connection error")
            return
        # this part only executes on successful UDP connection
        request = "K:" + CURRENT_CHATROOM + ":" + USERNAME + END_MESSAGE_STRING
        success = send_udp_request(recepient_socket, request, user_to_send)
        if not success:
            insert_message_in_command_window('[POKE_ERROR] Error sending poke message')
            return

        try:
            response, server = recepient_socket.recvfrom(1000)
            response = response.decode('ascii')
        except Exception as emsg:
            print('[POKE_ERROR] Poke Unsuccessful ' + str(emsg))
            insert_message_in_command_window('[POKE_ERROR]  Poke Unsuccessful')
            return
        if response == 'A::\r\n':
            insert_message_in_command_window('Successfully poked ' + user_to_poke)


def do_Quit():
    print("Do quit being called")
    global KEEP_ALIVE_THREAD, ROOM_SERVER_CHAT_SOCKET, POKE_SOCKET, MESSAGE_LISTENER_THREAD, FORWARD_LINK_THREAD, BACKWARD_THREAD, POKE_THREAD

    if KEEP_ALIVE_THREAD:
        print('Closing KEEPALIVE Thread')
        KEEP_ALIVE_THREAD.event.set()
        KEEP_ALIVE_THREAD.join()
    if BACKWARD_THREAD:
        print('Closing backward thread')
        BACKWARD_THREAD.event.set()
        BACKWARD_THREAD.join()
    if FORWARD_LINK_THREAD:
        print("Closing forwrd link thread")
        FORWARD_LINK_THREAD.event.set()
        FORWARD_LINK_THREAD.join()

    if MESSAGE_LISTENER_THREAD:
        print("Closing message listener thread")
        MESSAGE_LISTENER_THREAD.event.set()
        MESSAGE_LISTENER_THREAD.join()
    if POKE_THREAD:
        print("Closing poke thread")
        POKE_THREAD.event.set()
        POKE_THREAD.join()
    if ROOM_SERVER_CHAT_SOCKET:
        print('Shutting down room server socket')
        ROOM_SERVER_CHAT_SOCKET.close()
    if POKE_SOCKET:
        print('Shutting down poke socket')
        POKE_SOCKET.close()
    if FORWARD_LINK_SOCKET:
        print('Closing Forward Link socket')
        FORWARD_LINK_SOCKET.close()
    if len(BACKWARD_LINK_ARRAY) > 0:
        while BACKWARD_LINK_ARRAY:
            id, sock = BACKWARD_LINK_ARRAY.popitem()
            sock.close()
        print("Backward links removed")
    print("All resources released")
    win.destroy()
    print("window destroyed")
    sys.exit(0)


#
# Set up of Basic UI
#
win = Tk()
win.title("MyP2PChat")

# Top Frame for Message display
topframe = Frame(win, relief=RAISED, borderwidth=1)
topframe.pack(fill=BOTH, expand=True)
topscroll = Scrollbar(topframe)
MsgWin = Text(topframe, height='15', padx=5, pady=5, fg="red", exportselection=0, insertofftime=0)
MsgWin.pack(side=LEFT, fill=BOTH, expand=True)
topscroll.pack(side=RIGHT, fill=Y, expand=True)
MsgWin.config(yscrollcommand=topscroll.set)
topscroll.config(command=MsgWin.yview)

# Top Middle Frame for buttons
topmidframe = Frame(win, relief=RAISED, borderwidth=1)
topmidframe.pack(fill=X, expand=True)
Butt01 = Button(topmidframe, width='6', relief=RAISED, text="User", command=do_User)
Butt01.pack(side=LEFT, padx=8, pady=8);
Butt02 = Button(topmidframe, width='6', relief=RAISED, text="List", command=do_List)
Butt02.pack(side=LEFT, padx=8, pady=8);
Butt03 = Button(topmidframe, width='6', relief=RAISED, text="Join", command=do_Join)
Butt03.pack(side=LEFT, padx=8, pady=8);
Butt04 = Button(topmidframe, width='6', relief=RAISED, text="Send", command=do_Send)
Butt04.pack(side=LEFT, padx=8, pady=8);
Butt06 = Button(topmidframe, width='6', relief=RAISED, text="Poke", command=do_Poke)
Butt06.pack(side=LEFT, padx=8, pady=8);
Butt05 = Button(topmidframe, width='6', relief=RAISED, text="Quit", command=do_Quit)
Butt05.pack(side=LEFT, padx=8, pady=8);

# Lower Middle Frame for User input
lowmidframe = Frame(win, relief=RAISED, borderwidth=1)
lowmidframe.pack(fill=X, expand=True)
userentry = Entry(lowmidframe, fg="blue")
userentry.pack(fill=X, padx=4, pady=4, expand=True)

# Bottom Frame for displaying action info
bottframe = Frame(win, relief=RAISED, borderwidth=1)
bottframe.pack(fill=BOTH, expand=True)
bottscroll = Scrollbar(bottframe)
CmdWin = Text(bottframe, height='15', padx=5, pady=5, exportselection=0, insertofftime=0)
CmdWin.pack(side=LEFT, fill=BOTH, expand=True)
bottscroll.pack(side=RIGHT, fill=Y, expand=True)
CmdWin.config(yscrollcommand=bottscroll.set)
bottscroll.config(command=CmdWin.yview)


# ------------------------#
def main():
    if len(sys.argv) != 4:
        print("P2PChat.py <server address> <server port no.> <my port no.>")
        sys.exit(2)
    # else arguments are correctly passed, parse the arguments here
    get_arguments_from_sys()
    # signal.signal(signal.SIGINT, signal_handler)
    win.mainloop()


if __name__ == "__main__":
    main()
