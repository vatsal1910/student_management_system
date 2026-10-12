from flask import Flask

test_app = Flask(__name__)

@test_app.route("/")
def home():
    return "TEST SERVER IS WORKING"

@test_app.route("/test")
def test():
    return "TEST ROUTE IS WORKING"

if __name__ == "__main__":
    print("TEST SERVER STARTING...")
    test_app.run(
        host="127.0.0.1",
        port=5001,
        debug=False,
        use_reloader=False
    )