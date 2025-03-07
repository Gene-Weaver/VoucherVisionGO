import requests
from io import BytesIO

if __name__ == "__main__":
    # Server URL
    server_url = "https://vouchervision-go-738307415303.us-central1.run.app"

    # Authentication token (required)
    auth_token = "token"  # Get this from /login page or /signup

    # URL of the image you want to process
    image_url = "https://swbiodiversity.org/imglib/seinet/sernec/EKY/31234100396/31234100396116.jpg"

    # First, download the image
    print(f"Downloading image from: {image_url}")
    image_response = requests.get(image_url)
    if image_response.status_code != 200:
        print(f"Failed to download image: {image_response.status_code}")
        exit()

    # Get the filename from the URL
    image_filename = image_url.split("/")[-1]
    print(f"Image downloaded successfully: {image_filename}")

    # API endpoint
    url = f"{server_url}/process"

    # Prepare the multipart form data with the downloaded image
    files = {'file': (image_filename, BytesIO(image_response.content), 'image/jpeg')}

    # Optional parameters as list of tuples to allow multiple values for engines
    data = [
        ('engines', 'gemini-1.5-pro'),
        ('engines', 'gemini-2.0-flash'),
        ('prompt', 'SLTPvM_default.yaml')
    ]

    # Authentication header
    headers = {"Authorization": f"Bearer {auth_token}"}

    # Send the request
    print(f"Sending request to VoucherVision API: {url}")
    response = requests.post(url, files=files, data=data, headers=headers)

    # Process the response
    if response.status_code == 200:
        results = response.json()
        print("Image processed successfully!")
        print(results)
    else:
        print(f"Error: {response.status_code} - {response.text}")