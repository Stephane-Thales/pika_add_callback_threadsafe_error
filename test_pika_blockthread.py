# %% import packages
# connect to Rabbit MQ
import pika
# intercept stop signal
import signal
# print exception
import traceback
# threading
import functools
import threading
from queue import Queue
# logs time
import datetime
import time

# %% Function Message Acknowledgement
def ack_message(ch, delivery_tag):
    """Note that `ch` must be the same pika channel instance via which
    the message being ACKed was retrieved (AMQP protocol constraint).
    """
    print(f'DEBUG ack_message : begining of ack_message function')

    if ch.is_open:
        ch.basic_ack(delivery_tag)
        print(f'DEBUG ack_message : Acknowledgement delivered')
    else:
        # Channel is already closed, so we can't ACK this message;
        # log and/or do something that makes sense for your app in this case.
        print(datetime.datetime.now(),str(datetime.timedelta(seconds=time.time() - init_time)),f'ERROR Channel Closed when trying to Acknowledge')
        pass

# %% Function Process multiple messages in separate thread 
def block_process():
    # list global variables to be changed
    global channel
    # init local variables
    body_list = list()
    tag_list = list()

    print(f'DEBUG block_process : start of block_process function')

    # cancel the timer if exist, as we will proces all elements in the queue here
    if event and event.isAlive():
        event.cancel()

    # extract all queued messages fom internal python queue and rebuild individual listes body and tag from tupple
    for i in range(list_Boby_Tag.qsize()):
        myTuppleBodyTag = list_Boby_Tag.get()
        body_list += [myTuppleBodyTag[0]]
        tag_list += [myTuppleBodyTag[1]]
    # that also empty the queue

    # do something that take time with the block of nessage in body_list
    time.sleep(10)
    for body in body_list:
        body_str = body.decode()
        print(f'DEBUG block_process : message processed is {body_str}')

    # acknowledging all tags in tag_list by using the channel thread safe function .connection.add_callback_threadsafe
    for tag in tag_list:
        print(f'DEBUG preprare delivering Acknowledgement from thread')
        cb = functools.partial(ack_message, channel, tag)
        channel.connection.add_callback_threadsafe(cb)

    print(f'DEBUG block_process : end of block_process function')

    return

# %% Function Process message by message and call 
def process_message(ch, method, properties, body):
    # list global variables to be changed
    global list_Boby_Tag
    global event
    global threads

    # do nothing if this flag is on, as the program is about to close
    if PauseConsume == 1:
        return
    
    # cancel the timer if exist as we are going to process a block or restart a new timer
    if event and event.isAlive():
        event.cancel()

    # put in the queue the data from the body and tag as tupple
    list_Boby_Tag.put((body,method.delivery_tag))

    # if a max queue size is reached (here 500), immmediately launch a new thread to process the queue
    if list_Boby_Tag.qsize() == 500 :
        #print(f'DEBUG thread count before {len(threads)}')
        # keep in the threads list only the thread still running
        threads = [x for x in threads if x.is_alive()]
        #print(f'DEBUG thread count after {len(threads)}')
        # start the inference in a separated thread
        t = threading.Thread(target=block_process)
        t.start()
        # keep trace of the thread so it can be waited at the end if still running
        threads.append(t)
        #print(f'DEBUG thread count after add {len(threads)}')
    elif list_Boby_Tag.qsize() > 0 :
        # if the queue is not full create a thread with a timer to do the process after sometime, here 10 seconds for test purpose
        event = threading.Timer(interval=10, function=block_process)
        event.start()
        # also add this thread to the list of threads
        threads.append(event)

# %% PARAMETERS
RabbitMQ_host = '192.168.1.190'
RabbitMQ_port = 5672
RabbitMQ_queue = 'test_ctrlC'
RabbitMQ_cred_un = 'xxx'
RabbitMQ_cred_pd = 'xxx'

# %% init variables for batch process
list_Boby_Tag = Queue()
threads = list()
event = None
PauseConsume = 0
init_time = time.time()

# %% connect to RabbitMQ via Pika
cred = pika.credentials.PlainCredentials(RabbitMQ_cred_un,RabbitMQ_cred_pd)
connection = pika.BlockingConnection(pika.ConnectionParameters(host=RabbitMQ_host, port=RabbitMQ_port, credentials=cred))
channel = connection.channel()
channel.queue_declare(queue=RabbitMQ_queue,durable=True)
# tell rabbitMQ to don't dispatch a new message to a worker until it has processed and acknowledged the previous one :
channel.basic_qos(prefetch_count=1)

# %% define the comsumer
channel.basic_consume(queue=RabbitMQ_queue,
                      auto_ack=False, # false = need message acknowledgement : basic_ack in the callback
                      on_message_callback=process_message)

# %% empty queue and generate test data
channel.queue_purge(queue=RabbitMQ_queue)
# wait few second so the purge can be check in the RabbitMQ ui
print(f'DEBUG main : queue {RabbitMQ_queue} purged')
connection.sleep(10)
# generate 10 test messages
for msgId in range(10):
    channel.basic_publish(exchange='',
                        routing_key=RabbitMQ_queue,
                        body=f'message{msgId}',
                        properties=pika.BasicProperties(
                            delivery_mode = pika.spec.PERSISTENT_DELIVERY_MODE
                        ))
print(f'DEBUG main : test messages created in {RabbitMQ_queue}')

# %% Function clean stop of pika connection in case of interruption or exception
def cleanClose():
    # tell the on_message_callback to do nothing 
    PauseConsume = 1
    # Wait for all threads to complete
    for thread in threads:
        thread.join()
    # stop pika connection after a short pause
    connection.sleep(3)
    channel.stop_consuming()
    connection.close()
    return

# %% Function handle exit signals
def exit_handler(signum, frame):
    print(datetime.datetime.now(),str(datetime.timedelta(seconds=time.time() - init_time)),f'Exit signal received ({signum})')
    cleanClose()
    exit(0)

signal.signal(signal.SIGINT, exit_handler) # send by a CTRL+C or modified Docker Stop
#signal.signal(signal.SIGTSTP, exit_handler) # send by a CTRL+Z Docker Stop

print(' [*] Waiting for messages. To exit press CTRL+C')
try:
    channel.start_consuming()
except Exception:
    print(datetime.datetime.now(),str(datetime.timedelta(seconds=time.time() - init_time)),f'Exception received within start_consumming')
    traceback.print_exc()
    cleanClose()

# %% ISSUES
# FIXME : CtrlC freeze the channel that don't process the .connection.add_callback_threadsafe during the thread.join()
