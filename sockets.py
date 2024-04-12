import base64
import os
import json
import logging
from flask import Flask, render_template
from flask_sock import Sock
from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse
from langchain_google_genai import ChatGoogleGenerativeAI
from transcription import SpeechClientBridge
from google.cloud.speech import RecognitionConfig, StreamingRecognitionConfig
import threading
from langchain_core.prompts import ChatPromptTemplate
from langchain_google_vertexai import ChatVertexAI



app = Flask(__name__)
sockets = Sock(app)

HTTP_SERVER_PORT = 5000
TIWILIO_SAMPLE_RATE = 800  # Hz

# Twilio configuration
account_sid = os.environ['TWILIO_ACCOUNT_SID']
auth_token = os.environ['TWILIO_AUTH_TOKEN']
client = Client(account_sid, auth_token)
TWILIO_NUMBER=os.environ['TWILIO_NUMBER']

# Google configuration
GOOGLE_PROJECT_ID = os.environ['GOOGLE_PROJECT_ID']
GOOGLE_API_KEY=os.environ['GOOGLE_API_KEY']
GOOGLE_LANGUAGE_CODE = 'en-US'


# Flask settings
PORT = 5000
DEBUG = False
INCOMING_CALL_ROUTE = '/'

# LangChain Google Generative AI setup
llm = ChatGoogleGenerativeAI(model="gemini-pro", google_api_key=GOOGLE_API_KEY)

config = RecognitionConfig(
    encoding=RecognitionConfig.AudioEncoding.MULAW,
    sample_rate_hertz=8000,
    language_code="en-US",
)
streaming_config = StreamingRecognitionConfig(config=config, interim_results=True)


@app.route("/twiml", methods=["POST"])
def return_twiml():
    print("POST TwiML")
    return render_template("streams.xml")


def on_transcription_response(response):
    transcription = ""  # Define response2 outside the loop

    if not response.results:
        return

    result = response.results[0]
    if not result.alternatives:
        return
    
    for result in response.results:
        if result.is_final:
            transcription = result.alternatives[0].transcript
            print("Transcription: " + transcription)
            chat(transcription)
    

def chat(results):
    response1=VoiceResponse()
    system = "You are a helpful virtual agent who helps keep track of how the patient feels"
    human_message = f'{results}'

    # Create a ChatPromptTemplate with system and human messages
    prompt = ChatPromptTemplate.from_messages([
        ("system", system),
        ("human", human_message)
    ])


    chat = ChatVertexAI(project=GOOGLE_PROJECT_ID, temperature=0.7)

    chain = prompt | chat

    for chunk in chain.stream({}):
        print(chunk.content)
        response1.say(chunk.content)

@sockets.route('/realtime')
def handle_media(ws):
    """Handles incoming media (audio) data from the Twilio call over a WebSocket connection."""
    app.logger.info("Connection accepted")
    bridge = SpeechClientBridge(streaming_config, on_transcription_response)
    t = threading.Thread(target=bridge.start)
    t.start()

    while True:
        message = ws.receive()
        if message is None:
            bridge.add_request(None)
            bridge.terminate()
            break

        data = json.loads(message)
        match data['event']:
            case "connected":
                print('twilio connected')
                continue
            case "start":
                print('twilio started')
                continue
            case "media": 
                payload_b64 = data['media']['payload']
                chunk = base64.b64decode(payload_b64)
                bridge.add_request(chunk)
            case "stop":
                print('twilio stopped')
                break

    bridge.terminate()
    print("WS connection closed")

@app.route('/', methods=['GET', 'POST'])
def make_call(phone_number="+12403980310"):
    """Initiates an outbound call using Twilio."""
    # Generate the TwiML to connect the call to the WebSocket for media handling
    twiml = f"""
    <Response>
        <Say>
            What is your name?
        </Say>
        <Connect>
            <Stream url="wss://86ec-2601-282-1d80-7b00-9d88-8f2b-fc90-fd27.ngrok-free.app/realtime" />
        </Connect>
    </Response>
    """.strip()

    # Make the outbound call
    call = client.calls.create(
        twiml=twiml,
        from_=TWILIO_NUMBER,
        to=phone_number,
    )
    return str(call.sid)

make_call("+12403980310")  # Uncomment this line to make the call when the application is run

if __name__ == '__main__':
    app.logger.setLevel(logging.DEBUG)
    app.run(port=PORT, debug=DEBUG)
