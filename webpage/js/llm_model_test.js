// LLM Model Selection Test Script
// Add this to a test HTML page or run in browser console

// Function to monitor and verify LLM model selection
function testLlmModelSelection() {
  console.log("===== LLM Model Selection Test =====");
  
  // 1. Get the current selection
  const currentSelection = getSelectedModel();
  console.log(`Current LLM model selection: ${currentSelection}`);
  
  // 2. Create a test FormData to verify model is included
  const testFormData = createTestFormData();
  console.log("Test FormData contents:", getFormDataEntries(testFormData));
  
  // 3. Test changing the selection
  console.log("Testing selection change...");
  const radioButtons = document.querySelectorAll('input[name="llm_model"]');
  
  // Find a different option than current
  let differentOption = null;
  for (const radio of radioButtons) {
    if (radio.value !== currentSelection && !radio.disabled) {
      differentOption = radio;
      break;
    }
  }
  
  if (differentOption) {
    console.log(`Changing selection to: ${differentOption.value}`);
    differentOption.checked = true;
    
    // Trigger change event
    const event = new Event('change');
    differentOption.dispatchEvent(event);
    
    // Verify change was detected
    const newSelection = getSelectedModel();
    console.log(`New LLM model selection: ${newSelection}`);
    
    // Create a new test FormData to verify model is updated
    const updatedFormData = createTestFormData();
    console.log("Updated FormData contents:", getFormDataEntries(updatedFormData));
    
    if (newSelection === differentOption.value) {
      console.log("✅ Test PASSED: Model selection was updated correctly");
    } else {
      console.error("❌ Test FAILED: Model selection did not update correctly");
    }
  } else {
    console.log("No alternative model options available for testing");
  }
  
  console.log("===== Test Complete =====");
}

// Helper function to create a test FormData with current settings
function createTestFormData() {
  const formData = new FormData();
  
  // Add image URL (test value)
  formData.append('image_url', 'https://example.com/test-image.jpg');
  
  // Add selected engines
  getSelectedEngines().forEach(engine => {
    formData.append('engines', engine);
  });
  
  // Add OCR only mode if selected
  if ($('#ocrOnly').is(':checked')) {
    formData.append('ocr_only', 'true');
  }
  
  // Add prompt template if specified
  const promptTemplate = $('#promptTemplate').val();
  if (promptTemplate) {
    formData.append('prompt', promptTemplate);
  }
  
  // Add selected model
  const llm_model = getSelectedModel();
  if (llm_model) {
    formData.append('llm_model', llm_model);
  }
  
  return formData;
}

// Helper function to extract FormData entries for display
function getFormDataEntries(formData) {
  const entries = [];
  for (const pair of formData.entries()) {
    entries.push({ key: pair[0], value: pair[1] });
  }
  return entries;
}

// Run the test
testLlmModelSelection();tes