import requests


def main():
    r = requests.get('http://127.0.0.1:5000/login')
    print(r.status_code)
    print(len(r.text))
    print(r.text[:200])


if __name__ == '__main__':
    main()
