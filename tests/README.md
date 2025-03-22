### Batch URL Processing

Process multiple images from a list of URLs:

1. Upload a text file (.txt) with one URL per line, or a CSV file with URLs in a column
2. For CSV files, specify the column name containing URLs (default: "url")
3. Set the number of concurrent requests (1-10)
4. Click "Process URLs"
5. Monitor progress and view results
6. Once processing is complete, you have three download options:
   - **Download Summary CSV**: Basic information including URL, status, error messages, and OCR engines used
   - **Download Results CSV**: Detailed spreadsheet with each JSON field as a separate column
   - **Download Results JSON**: ZIP archive containing individual JSON files named after each processed URL's filename

Example text file format:
```
https://example.com/image1.jpg
https://example.com/image2.jpg
https://example.com/image3.jpg
```

Example CSV file format:
```
url,description,category
https://example.com/image1.jpg,Specimen 1,Category A
https://example.com/image2.jpg,Specimen 2,Category B
https://example.com/image3.jpg,Specimen 3,Category C
```# VoucherVision API Test Tool

This web-based tool allows you to test the VoucherVision API with different types of inputs:

- Single image file upload
- Single image URL
- Batch processing of URLs from text or CSV files
- Batch processing of local image folders

## Getting Started

### Running Locally

1. Clone the repository or download the files
2. Start a local server in the project directory:
   ```
   python -m http.server 8000
   ```
3. Open in your browser:
   ```
   http://localhost:8000/index.html
   ```

### Authentication

The tool supports two authentication methods:

1. **API Key Authentication**: Recommended for batch processing and automated workflows
2. **Auth Token Authentication**: For browser-based testing using Firebase tokens

You'll need to provide valid credentials before using any of the API features.

## Features

### General Settings

- **Authentication Method**: Choose between API Key or Auth Token
- **OCR Only Mode**: Toggle to perform only OCR without processing the extracted text
- **Engines**: Select which OCR engines to use (gemini-1.5-pro, gemini-2.0-flash)
- **Prompt Template**: Specify a custom prompt template for processing

### Single File Upload

Upload and process a single image file:

1. Select an image file from your computer
2. Review the image preview
3. Click "Upload and Process"
4. View the API response results

### Single Image URL

Process an image from a URL:

1. Enter the image URL
2. Test URL availability (optional)
3. Click "Process URL"
4. View the API response results

 the column name containing URLs (default: "url")
3. Set the number of concurrent requests (1-10)
4. Enable "Save results to CSV" if you want a downloadable results file
5. Click "Process URLs"
6. Monitor progress and view results

Example text file format:
```
https://example.com/image1.jpg
https://example.com/image2.jpg
https://example.com/image3.jpg
```

Example CSV file format:
```
url,description,category
https://example.com/image1.jpg,Specimen 1,Category A
https://example.com/image2.jpg,Specimen 2,Category B
https://example.com/image3.jpg,Specimen 3,Category C
```

### Batch Folder Processing

Process multiple image files from your computer:

1. Select multiple image files using the file picker or drag and drop files onto the drop zone
2. Set the number of concurrent requests (1-10)
3. Click "Process Images"
4. Monitor progress and view results
5. Once processing is complete, you have three download options:
   - **Download Summary CSV**: Basic information including filename, size, status, error messages, and OCR engines used
   - **Download Results CSV**: Detailed spreadsheet with each JSON field as a separate column
   - **Download Results JSON**: ZIP archive containing individual JSON files named after each processed image file

## Processing Options

- **OCR Only Mode**: When enabled, only performs OCR without additional processing
- **Concurrent Requests**: Control how many images are processed simultaneously (higher values increase speed but may encounter rate limiting)
- **Save to CSV**: Generate a downloadable CSV file with processing results

## Debugging

The tool includes a debug section at the bottom of the page that logs all operations and API interactions. This is useful for troubleshooting issues or understanding the API flow.

## CORS Support

The tool includes a "Test CORS Support" button to verify that your browser can successfully communicate with the VoucherVision API.

## Best Practices

1. **Start with Single Files**: Test with single files before attempting batch processing
2. **Limit Concurrency**: Start with lower concurrency (3-5) and increase if needed
3. **Use API Keys**: For batch processing, API keys generally offer better performance than auth tokens
4. **Check File Types**: Ensure your image files are in supported formats (PNG, JPG, JPEG, GIF, TIF, TIFF)
5. **Monitor Quotas**: Be aware of any API usage limits associated with your credentials