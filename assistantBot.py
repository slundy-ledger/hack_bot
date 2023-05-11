import os
import uuid
import json
import openai
import pinecone
import re
import requests

from dotenv import load_dotenv
from eth_account.messages import encode_defunct
from flask import Flask, jsonify, make_response, redirect, render_template, request

from langchain.chat_models import ChatOpenAI
from langchain.memory import ChatMessageHistory

from web3 import Web3

from data import ABI, ADDRESS, FAKE_RESPONSE, primer, browser_headers


load_dotenv()

history = ChatMessageHistory()

env_vars = [
    "OPENAI_API_KEY",
    # "SERPAPI_API_KEY",
    "ALCHEMY_API_KEY",
    "PINECONE_API_KEY",
    "PINECONE_ENVIRONMENT",
]

os.environ.update({key: os.getenv(key) for key in env_vars})
os.environ[
    "WEB3_PROVIDER"
] = f"https://polygon-mumbai.g.alchemy.com/v2/{os.environ['ALCHEMY_API_KEY']}"
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
PINECONE_ENVIRONMENT = os.getenv("PINECONE_ENVIRONMENT")
ORGANIZATION = os.getenv("ORGANIZATION")

# Initialize web3
web3 = Web3(Web3.HTTPProvider(os.environ["WEB3_PROVIDER"]))

# Initialize LLM
llm = ChatOpenAI(
    openai_api_key=os.environ["OPENAI_API_KEY"],
    temperature=0.1,
    model_name="gpt-3.5-turbo"
    # model_name='gpt-4'
)


# Prepare augmented query

pinecone.init(
    api_key=os.environ["PINECONE_API_KEY"],
    enviroment=os.environ["PINECONE_ENVIRONMENT"],
)
pinecone.whoami()
index_name = "hc"
# index_name = 'hctest'
index = pinecone.Index(index_name)

embed_model = "text-embedding-ada-002"

# #####################################################


# Define Flask app
app = Flask(__name__, static_folder="static")


# Define authentication function
def authenticate(signature):
    w3 = Web3(Web3.HTTPProvider(os.environ["WEB3_PROVIDER"]))
    message = "Access to chat bot"
    message_hash = encode_defunct(text=message)
    signed_message = w3.eth.account.recover_message(message_hash, signature=signature)
    balance = int(contract.functions.balanceOf(signed_message).call())
    if balance > 0:
        token = uuid.uuid4().hex
        response = make_response(redirect("/gpt"))
        response.set_cookie(
            "authToken", token, httponly=True, secure=True, samesite="strict"
        )
        return response
    else:
        return "You don't have the required NFT!"


# Define function to check for authToken cookie
def has_auth_token(request):
    authToken = request.cookies.get("authToken")
    return authToken is not None


# Define Flask endpoints
@app.route("/")
def home():
    return render_template("auth.html")


@app.route("/auth")
def auth():
    signature = request.args.get("signature")
    response = authenticate(signature)
    return response


@app.route("/gpt")
def gpt():
    if has_auth_token(request):
        return render_template("index.html")
    else:
        return redirect("/")


@app.route("/api", methods=["POST"])
def react_description():
    user_input = request.json.get("user_input")

    try:
        # response = FAKE_RESPONSE
        response = ask_gpt(user_input)

        print(response)
        # test_urls_from_response_okay(response)
        return {"output": response}

    except ValueError as e:
        print(e)
        return {"output": "Sorry, could you please repharse the question?"}


def ask_gpt(user_input: str) -> str:
    res_embed = openai.Embedding.create(input=[user_input], engine=embed_model)

    xq = res_embed["data"][0]["embedding"]

    res_query = index.query(xq, top_k=5, include_metadata=True)

    contexts = [item["metadata"]["text"] for item in res_query["matches"]]

    augmented_query = (
        "\n\n---\n\n".join(contexts)
        + "\n\n-----\n\n"
        + user_input
        + "? Please provide a comprehensive answer to the question, and make sure to incorporate relevant URL links from the previous context. Do not enclose the links in parentheses. Don't share a link that is not included in the previous context. Never share links containing 'academy' in the URL. Important : format your response using markdown syntax. When writing a list, use dash instead of numbers."
    )

    res = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        temperature=0.1,
        # model="gpt-4",
        messages=[
            {"role": "system", "content": primer},
            {"role": "user", "content": augmented_query},
        ],
    )

    return res["choices"][0]["message"]["content"]


def test_urls_from_response_okay(text: str):
    url_pattern = re.compile(r"https?://\S+")
    urls = re.findall(url_pattern, text)
    formatted_urls = [url.rstrip(".") for url in urls]
    for url in formatted_urls:
        if "academy" in url:
            raise ValueError(url)

        res = requests.head(url, headers=browser_headers)
        if res.status_code in [401, 403, 404]:
            # always get 403, ledger is protected from bot even with browser headers
            raise ValueError(url)


contract = web3.eth.contract(address=ADDRESS, abi=ABI)

# Start the Flask app
if __name__ == "__main__":
    app.run(port=8000, debug=True)
