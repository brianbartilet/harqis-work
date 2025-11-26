import json
import paho.mqtt.client as mqtt

MQTT_HOST = "your.server.ip"
MQTT_PORT = 1883
MQTT_USER = "youruser"
MQTT_PASS = "yourpass"
TOPIC = "owntracks/#"  # subscribe to all owntracks messages

def on_connect(client, userdata, flags, rc):
    print("Connected with result code", rc)
    client.subscribe(TOPIC)

def on_message(client, userdata, msg):
    try:
        payload = msg.payload.decode("utf-8")
        data = json.loads(payload)
    except Exception as e:
        print("Failed to decode message:", e)
        return

    # OwnTracks location messages usually have 'lat' and 'lon'
    lat = data.get("lat")
    lon = data.get("lon")
    tst = data.get("tst")  # unix timestamp
    acc = data.get("acc")  # accuracy in meters, optional

    print(f"Topic: {msg.topic}")
    print(f"Location: lat={lat}, lon={lon}, acc={acc}, tst={tst}")
    print("---")

client = mqtt.Client()
client.username_pw_set(MQTT_USER, MQTT_PASS)
client.on_connect = on_connect
client.on_message = on_message

client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
client.loop_forever()
