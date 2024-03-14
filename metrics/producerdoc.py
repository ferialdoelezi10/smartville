# This file is part of the "Smartville" project.
# Copyright (c) 2024 University of Insubria
# Licensed under the Apache License 2.0.
# SPDX-License-Identifier: Apache-2.0
# For the full text of the license, visit:
# https://www.apache.org/licenses/LICENSE-2.0

# Smartville is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# Apache License 2.0 for more details.

# You should have received a copy of the Apache License 2.0
# along with Smartville. If not, see <https://www.apache.org/licenses/LICENSE-2.0>.

# Additional licensing information for third-party dependencies
# used in this file can be found in the accompanying `NOTICE` file.
from confluent_kafka import Producer, KafkaException
from confluent_kafka.admin import AdminClient, NewTopic
import time
import psutil
import getpass
import subprocess
import threading
import math
import os

bootstrap_servers = 'kafka:29092'
pinghost = "www.google.com"
round_trip_time = None
end_message = str(math.nan).encode('utf-8')

# Definizione callback per il report dei messaggi inviati

def delivery_report(err, msg):
    if err is not None:
        print(f"Messaggio non inviato: {err}")
    else:
        print(f"Valore {msg.value().decode('utf-8')} inviato al topic {msg.topic()}, partizione {msg.partition()}, offset {msg.offset()}")

# Controllo sull'esistenza di un topic all'interno del cluster

def topic_exists(bootstrap_servers, topic_name):
    admin_client = AdminClient({'bootstrap.servers': bootstrap_servers})

    try:
        metadata = admin_client.list_topics(timeout=10)
        topics = metadata.topics

        if topic_name in topics:
            return True
        else:
            return False

    except KafkaException as e:
        print(f"Error: {e}")
        return False

# Creazione di un topic all'interno del cluster

def create_topic(bootstrap_servers, topic_name, num_partitions, replication_factor):
    admin_client = AdminClient({'bootstrap.servers': bootstrap_servers})

    new_topic = NewTopic(topic_name, num_partitions, replication_factor)

    admin_client.create_topics([new_topic])
    try:
        time.sleep(10)
    except Exception as e:
        print(f"Errore nel creare il topic '{topic_name}': {e}")

# Thread dedicato al calcolo della latenza

def ping_thread(host):
    while(True):
        global round_trip_time
        try:
            # Processo latenza con timeout settato a 4.8s
            result = subprocess.run(["ping", "-c", "1", pinghost], capture_output=True, text=True, timeout=4.8)

            # Estrazione output
            output = result.stdout

            lines = output.split('\n')

            # Estrazone valore latenza dal messaggio di uscita
            for line in lines:
                if "time=" in line:
                    time_index = line.find("time=")
                    time_str = line[time_index + 5:].split()[0]
                    round_trip_time = float(time_str)
                    break
            

        except subprocess.TimeoutExpired:
            print("Richiesta del ping scaduta.")
            round_trip_time = None

        time.sleep(1)



#topic_name = "test99"

# Seleziona il topic in base al nome del container (questo nel caso di avvio produttore in docker)

container_name = os.getenv('HOSTNAME')
if container_name is not None:
    print(f"Nome del container: {container_name}")
else:
    print("Impossibile ricevere nome container.")

topic_name = container_name

# Definizione numero di partizioni di un nuovo topic

num_partitions = 5
replication_factor = 1

exists = topic_exists(bootstrap_servers, topic_name)

# Controllo di esistenza topic, nel caso questo non esistesse, ne verrà creato uno nuovo

if exists:
    print(f"Il topic '{topic_name}' esiste.")
else:
    print(f"Il topic '{topic_name}' non esiste.")
    create_topic(bootstrap_servers, topic_name, num_partitions, replication_factor)
    exists = topic_exists(bootstrap_servers, topic_name)
    if exists:
        print(f"Topic '{topic_name}' creato con successo.")
    else:
        print("Utente non presente su Kafka server, impossibile procedere")

# Inserimento metriche nel server

if exists:
    conf = {'bootstrap.servers': bootstrap_servers}
    producer = Producer(conf)

    try:
        first = True

        while True:

            
            # Modulo per l'ottenimento metrica CPU
            try:
                percpu = psutil.cpu_percent(interval=1) # Attendo 1 secondo
                
                # Inserimento metrica CPU nel topic con partizione 0
                producer.produce(topic=topic_name, value=str(percpu), partition=0, callback=delivery_report)
                producer.flush()

            except FileNotFoundError:
                print("Informazioni CPU non disponibili")
                producer.produce(topic=topic_name, value=end_message, partition=0, callback=delivery_report)
                producer.flush()
       
            time.sleep(1) # Attendo 1 secondo

            # Modulo per l'ottenimento metrica sulla RAM
            try:
                ram_info = psutil.virtual_memory() 
                valram = round(ram_info.used / 1024 / 1024 / 1024, 2)

                # Inserimento metrica RAM nel topic con partizione 1
                producer.produce(topic=topic_name, value=str(valram), partition=1, callback=delivery_report)
                producer.flush()

                #perram = ram_info.percent
            
            except FileNotFoundError:
                print("Informazioni RAM non disponibili")
                producer.produce(topic=topic_name, value=end_message, partition=1, callback=delivery_report)
                producer.flush()

            time.sleep(1) # Attendo 1 secondo

            # Modulo per l'ottenimento del ping
            try:

                if (first == False):
                    if round_trip_time is not None:

                        # Inserimento metrica latenza nel topic con partizione 2
                        producer.produce(topic=topic_name, value=str(round_trip_time), partition=2, callback=delivery_report)
                        producer.flush()

                    else:
                        producer.produce(topic=topic_name, value=end_message, partition=2, callback=delivery_report)
                        producer.flush()

                # Il thread dedicato al processo di ottenimento del ping viene avviato durante il primo ciclo
                else:
                    ping_thread = threading.Thread(target=ping_thread, args=(pinghost,))
                    ping_thread.daemon = True  # Impostato a daemon così termina solo quando il programma finisce
                    ping_thread.start()

            except FileNotFoundError:
                print("Informazioni latenza non disponibili")
                producer.produce(topic=topic_name, value=end_message, partition=2, callback=delivery_report)
                producer.flush()

            time.sleep(1) # Attendo 1 secondo

            # Modulo per l'ottenimento del traffico in entrata
            if (first == False):
                try:
                    updated_stats_incoming = psutil.net_io_counters()
                    end_time_incoming = time.time()
                    time_incoming = end_time_incoming - start_time_incoming

                    # Il traffico in entrata viene ottenuto facendo la differenza fra traffico in inziale e finale diviso il tempo trascorso
                    incoming_traffic = (updated_stats_incoming.bytes_recv - initial_stats_incoming.bytes_recv) / time_incoming  
                    incoming_traffic_size = round(incoming_traffic / 1024, 2)
                
                    # Inserimento metrica sul traffico in entrata nel topic con partizione 3
                    producer.produce(topic=topic_name, value=str(incoming_traffic_size), partition=3, callback=delivery_report)
                    producer.flush()

                    # Reimpostazione valori iniziali
                    start_time_incoming = end_time_incoming
                    initial_stats_incoming = updated_stats_incoming

                except FileNotFoundError:
                    print("Informazioni dati rete non disponibili")
                    producer.produce(topic=topic_name, value=end_message, partition=3, callback=delivery_report)
                    producer.flush()
            else:
                try:

                    # Impostazioni valori iniziali nel primo ciclo
                    initial_stats_incoming = psutil.net_io_counters()
                    start_time_incoming = time.time()

                except FileNotFoundError:
                    print("Informazioni dati rete non disponibili")
                    producer.produce(topic=topic_name, value=end_message, partition=3, callback=delivery_report)
                    producer.flush()
                
            time.sleep(1) # Attendo 1 secondo
            
            # Modulo per l'ottenimento del traffico in uscita
            if (first == False):
                try:
                    updated_stats_outcoming = psutil.net_io_counters()
                    end_time_outcoming = time.time()
                    time_outcoming = end_time_outcoming - start_time_outcoming

                    # Il traffico in uscita viene ottenuto facendo la differenza fra traffico in inziale e finale diviso il tempo trascorso
                    outcoming_traffic = (updated_stats_outcoming.bytes_sent - initial_stats_outcoming.bytes_sent) / time_outcoming  
                    outcoming_traffic_size = round(outcoming_traffic / 1024, 2)

                    producer.produce(topic=topic_name, value=str(outcoming_traffic_size), partition=4, callback=delivery_report)
                    producer.flush()

                    # Reimpostazione valori iniziali
                    start_time_outcoming = end_time_outcoming
                    initial_stats_outcoming = updated_stats_outcoming

                except FileNotFoundError:
                    print("Informazioni dati rete non disponibili")
                    producer.produce(topic=topic_name, value=end_message, partition=4, callback=delivery_report)
                    producer.flush()
            else:
                try:

                    # Impostazioni valori iniziali nel primo ciclo
                    initial_stats_outcoming = psutil.net_io_counters()
                    start_time_outcoming = time.time()

                except FileNotFoundError:
                    print("Informazioni dati rete non disponibili")
                    producer.produce(topic=topic_name, value=end_message, partition=4, callback=delivery_report)
                    producer.flush()

            first = False


    except Exception as e:
        print(str(e).capitalize())

    except KeyboardInterrupt:

        # In caso di interruzione del programma, vengono inviati valori NaN da parte del produttore

        for i in range(5):
            producer.produce(topic=topic_name, value=end_message, partition=i, callback=delivery_report)
            producer.flush()
        
        print("Programma terminato!")