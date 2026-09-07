import json
def evaluate(_path):
    return {'combined_score': 0.0}
if __name__ == '__main__':
    print(json.dumps(evaluate('initial_program.py')))
