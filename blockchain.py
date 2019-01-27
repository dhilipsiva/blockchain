from sys import argv
from time import time
from uuid import uuid4
from json import dumps
from hashlib import sha256
from dataclasses import dataclass
from typing import List, Set, Dict

import requests
from sanic import Sanic
from sanic.response import json
from dataclasses_json import DataClassJsonMixin


CHAIN_ENDPOINT = 'chain'


class DataClassMixin(object):
    def to_json(self) -> str:
        return json.dumps(
            self, default=lambda o: o.__dict__, sort_keys=True, indent=4)


@dataclass
class Transaction(DataClassJsonMixin):
    '''
    dataclass representing a Transaction object
    '''
    sender: str
    recipient: str
    amount: float


@dataclass
class Block(DataClassJsonMixin):
    '''
    dataclass representing a Block object
    '''
    index: int
    timestamp: float
    transactions: List[Transaction]
    proof: int
    previous_hash: str

    @staticmethod
    def load(data: Dict):  # -> Block:
        transactions = data.pop('transactions')
        transactions = [Transaction(**item) for item in transactions]
        data['transactions'] = transactions
        return Block(**data)

    @staticmethod
    def load_many(items: List[Dict]):  # -> List[Block]:
        return [Block.load(item) for item in items]


def hash(data: str) -> str:
    '''
    Hashes a given data and return its hexdigest
    '''
    return sha256(data.encode()).hexdigest()


def block_hash(block: Block) -> str:
    '''
    Hashes the last block
    '''
    data = dumps(block.to_json(), sort_keys=True)
    return hash(data)


def valid_proof(last_proof: int, proof: int) -> bool:
    '''
    Check if a given proof is valid
    '''
    guess = hash(f'{last_proof}{proof}')
    return guess[:4] == "0000"


def proof_of_work(last_proof: int) -> int:
    '''
    A silly proof of work algorithm
    '''
    proof = 0
    while valid_proof(last_proof, proof) is False:
        proof += 1
    return proof


def valid_chain(chain: List[Block]) -> bool:
    '''
    Check if a chain is valid
    '''
    last_block = None
    for block in chain:
        if last_block is None:
            last_block = block
            continue
        if block.previous_hash != block_hash(last_block):
            return False
        if not valid_proof(last_block.proof, block.proof):
            return False
        last_block = block
    return True


@dataclass
class Blockchain(object):
    nodes: Set[str]
    chain: List[Block]
    unverified_transactions: List[Transaction]

    def __init__(self):
        '''
        Initialize a new bockchain
        '''
        self.chain = []
        self.nodes = set()
        self.unverified_transactions = []
        self.genesis_block()

    def register_node(self, address: str):
        '''
        Register a new p2p node, Ex: 0.0.0.0:8001
        '''
        self.nodes.add(address)

    @property
    def last_block(self) -> Block:
        '''
        Returns the last block in the chain
        '''
        return self.chain[-1]

    def new_transaction(
            self, sender: str, recipient: str, amount: int) -> Transaction:
        '''
        Create a new transaction
        takes in sender, recipient, amout
        returns the index of the next block
        '''
        transaction = Transaction(
            sender=sender, recipient=recipient, amount=amount)
        self.unverified_transactions.append(transaction)
        return transaction

    def new_block(self, proof: int, previous_hash: str) -> Block:
        '''
        Create new block and add it to the chain
        proof given by proof of work algoritm
        '''
        block = Block(
            transactions=self.unverified_transactions,
            index=len(self.chain) + 1, timestamp=time(), proof=proof,
            previous_hash=previous_hash or self.last_block_hash)
        self.unverified_transactions = []
        self.chain.append(block)
        return block

    def genesis_block(self) -> Block:
        '''
        Creates a genesis block
        '''
        return self.new_block(proof=100, previous_hash=1)

    def resolve_conflicts(self) -> bool:
        '''
        Get chains from all nodes and resolve any conflicts
        Our conflict resolutions stratergy is a simple replace :P
        '''
        replaced = False
        for node in self.nodes:
            response = requests.get(f'http://{node}/{CHAIN_ENDPOINT}')
            if response.status_code == 200:
                chain = response.json()['chain']
                chain = Block.load_many(chain)
                if len(chain) > len(self.chain) and valid_chain(chain):
                    self.chain = chain
                    replaced = True
        return replaced


app = Sanic(__name__)
blockchain = Blockchain()
node_identifier = str(uuid4()).replace('-', '')


@app.route('/', methods=['GET'])
def home(request):
    return json(blockchain)


@app.route(f'/{CHAIN_ENDPOINT}', methods=['GET'])
def chain(request):
    return json({'chain': blockchain.chain})


@app.route('/transactions', methods=['POST'])
def transactions(request):
    values = request.json
    required = ['sender', 'recipient', 'amount']
    if not all(k in values for k in required):
        return json({'required': required}, 400)
    transaction = blockchain.new_transaction(**values)
    return json({'transaction': transaction})


@app.route('/mine', methods=['GET'])
def mine(request):
    last_block = blockchain.last_block
    last_proof = last_block.proof
    proof = proof_of_work(last_proof)
    mining_fee = blockchain.new_transaction(
        sender="0", recipient=node_identifier, amount=1)
    previous_hash = block_hash(last_block)
    block = blockchain.new_block(proof, previous_hash)
    return json({
        'message': 'Mining Successful', 'block': block,
        'mining_fee': mining_fee})


@app.route('/consensus', methods=['GET'])
def consensus(request):
    replaced = blockchain.resolve_conflicts()
    return json({'replaced': replaced, 'chain': blockchain.chain})


@app.route('/nodes', methods=['POST'])
def nodes(request):
    node = request.json.get('node').strip()
    if node is None:
        return json({'message': '`node` required'}, 400)
    blockchain.register_node(node)
    return json({
        'message': 'New nodes have been added', 'nodes': blockchain.nodes})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=argv[1])
