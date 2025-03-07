import requests

if __name__ == "__main__":
    # Server URL
    server_url = "https://vouchervision-go-738307415303.us-central1.run.app"

    # Authentication token (required)
    auth_token = "token"  # Get this from /login page or /signup

    # API endpoint
    url = f"{server_url}/process"

    # Prepare the multipart form data
    files = {'file': open('D:/Dropbox/VoucherVisionGO-client/demo/images/MICH_16205594_Poaceae_Jouvea_pilosa_full.jpg', 'rb')}

    # Optional parameters
    data = {
        'engines': ['gemini-1.5-pro', 'gemini-2.0-flash'],  # OCR engines to use
        'prompt': 'SLTPvM_default.yaml'  # Custom prompt file
    }

    # Authentication header
    headers = {"Authorization": f"Bearer {auth_token}"}

    # Send the request
    response = requests.post(url, files=files, data=data, headers=headers)

    # Process the response
    if response.status_code == 200:
        results = response.json()
        print(results)
    else:
        print(f"Error: {response.status_code} - {response.text}")