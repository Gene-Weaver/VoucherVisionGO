# VoucherVisionGO API Guide

[VoucherVision is an AI transcription tool for museum specimens](https://bsapubs.onlinelibrary.wiley.com/doi/10.1002/ajb2.16256). There are several ways of using VoucherVision. This is the simplest. Here you can upload images or URLs and receive CSV or JSON files back. The [Hugging Face implementation](https://huggingface.co/spaces/phyloforfun/VoucherVision) and the [full GitHub version](https://github.com/Gene-Weaver/VoucherVision)  are designed to enable in-depth optimization of workflows, to test new AI models, and to prepare data for use with the [VoucherVision Editor application](https://github.com/Gene-Weaver/VoucherVisionEditor). If you don't need the VV Editor, you can use this API instead. 

The VoucherVisionGO API provides access to the best OCR/LLM combination for AI transcription - Google Gemini. We will update the VoucherVisionGO API as models continue to improve. 

This webpage is not the only way to use the VoucherVisionGO API. You can...
- Install the client from [PyPI](https://pypi.org/project/vouchervision-go-client/) where we provide some helper functions to make it easier to integrate into Python projects
- Clone the [VoucherVisionGO-client repo](https://github.com/Gene-Weaver/VoucherVisionGO-client) and integrate the client code directly
- Inspect the [code for this website](https://github.com/Gene-Weaver/VoucherVisionGO/tree/main/webpage) to see some options for interacting with the API
- Make your own GET/POST requests using guides in the [GitHub](https://github.com/Gene-Weaver/VoucherVisionGO-client) or [PyPI](https://pypi.org/project/vouchervision-go-client/) docs

## Getting Started
This webpage allows you to test the VoucherVisionGO API with different types of inputs:

- Single image file upload
- Single image URL 
- Batch processing of URLs from text or CSV files
- Batch processing of a folder containing images

The VoucherVisionGO API runs on Google Cloud Run, an on-demand server that may take up to one minute to wake from sleep. Once awake, each call takes approximately 20 seconds. At full utilization, the API can process about 4,000 images per hour. Please reach out if you plan to process thousands of images, as you may hit API limits.

It is possible to integrate VoucherVisionGO directly into Symbiota/Specify etc.

### Authentication

The VoucherVisionGO API supports two authentication methods:

1. **API Key Authentication**: Recommended for automated workflows (putting VVGO into your own application, Specify, Symbiota, etc.).
2. **Auth Token Authentication**: Browser-based authentication for shorter sessions, testing.

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

### Batch URL Processing

Process multiple images from a list of URLs:

1. Upload a text file (.txt) with one URL per line, or a CSV file with URLs in a column
2. For CSV files, specify the column name containing URLs (default: "url")
3. Set the number of concurrent requests (1-32)
4. Click "Process URLs"
5. Monitor progress and view results
6. Once processing is complete, you have four download options:
   - **Download Summary CSV**: Basic information including URL, status, error messages, and OCR engines used
   - **Download Results CSV**: Detailed spreadsheet with each JSON field as a separate column
   - **Download Results JSON**: ZIP archive containing individual JSON files named after each processed URL's filename
   - **Download Full JSON**: ZIP archive with complete API responses including all metadata

Example text file format:
```
https://example.com/image1.jpg
https://example.com/image2.jpg
https://example.com/image3.jpg
```

Example CSV file format:
| url | description | category |
| --- | ----------- | -------- |
| https://example.com/image1.jpg  | Specimen 1 | Category A |
| https://example.com/image2.jpg  | Specimen 2 | Category B |
| https://example.com/image3.jpg  | Specimen 3 | Category C |

### Batch Folder Processing

Process multiple image files from your computer:

1. Select multiple image files using the file picker or drag and drop files onto the drop zone
2. Set the number of concurrent requests (1-32)
3. Click "Process Images"
4. Monitor progress and view results
5. Once processing is complete, you have four download options:
   - **Download Summary CSV**: Basic information including filename, size, status, error messages, and OCR engines used
   - **Download Results CSV**: Detailed spreadsheet with each JSON field as a separate column
   - **Download Results JSON**: ZIP archive containing individual JSON files named after each processed image file
   - **Download Full JSON**: ZIP archive with complete API responses including all metadata

## Processing Options

- **OCR Only Mode**: When enabled, only performs OCR without additional processing
- **Concurrent Requests**: Control how many images are processed simultaneously (higher values increase speed but may encounter rate limiting)
- **Prompt Template**: Customize how the API processes extracted text

## Results Visualization

- **Image thumbnails**: Preview processed images in a gallery view
- **OCR Text**: View extracted text from images
- **Structured JSON**: Access formatted JSON output for structured data extraction
- **Error reporting**: Detailed error messages for failed processing attempts

## Debugging

The tool includes a debug section at the bottom of the page that logs all operations and API interactions. This is useful for troubleshooting issues or understanding the API flow.

## CORS Support

The tool includes a "Test CORS Support" button to verify that your browser can successfully communicate with the VoucherVisionGO API.

## Best Practices

1. **Start with Single Files**: Test with single files before attempting batch processing
2. **Limit Concurrency**: Start with lower concurrency (3-5) and increase if needed
3. **Use API Keys**: For batch processing, API keys generally offer better performance than auth tokens
4. **Check File Types**: Ensure your image files are in supported formats (PNG, JPG, JPEG, TIF, TIFF)
5. **Monitor Quotas**: Be aware of any API usage limits associated with your credentials

### Running Locally

This simple webpage can be used as a guide to implement VoucherVisionGO API in your project. You can look at the code to find examples of how to implement parallel calls or interact with the API. To look at the code:

1. Clone the repository or download the files. You don't need to install anything to host this webpage on your own computer.
2. Start a local server in the project directory:
   ```
   python -m http.server 8000
   ```
3. Open in your browser:
   ```
   http://localhost:8000/webpage/index.html
   ```