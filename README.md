# Cache Refresh Function – MyPlacementBuddy

A Python-based serverless function developed during my internship at **MyPlacementBuddy** to handle cache refresh operations and keep cached application data synchronized with updated information.

## 📌 Project Overview

The function is responsible for refreshing cached data when an update occurs in the application.

Instead of manually updating the cache, the function automates the refresh process by identifying the relevant cached data, processing the required information, and updating the cache accordingly.

## ⚙️ Functionality

The function handles cache refresh operations based on the state of the data and the availability of the required resources.

### Case 1: Cache/Data Available

When the required cached data is available:

```text
Request / Trigger
       ↓
Identify cached data
       ↓
Retrieve required information
       ↓
Process updated data
       ↓
Refresh cache
       ↓
Return successful response
```

The function processes the available information and refreshes the cache with the updated data.

### Case 2: Cache/Data Not Available

If the expected cached data is missing or unavailable, the function handles the situation without attempting an invalid update.

```text
Request / Trigger
       ↓
Check required data
       ↓
Data unavailable
       ↓
Handle exception / return appropriate response
```

This prevents the function from performing an incorrect cache operation.

### Case 3: External Service / Database Issue

If the function cannot retrieve the required information because of an issue with an external service or database, the error is handled through the function's error-handling mechanism.

```text
Request / Trigger
       ↓
Attempt data retrieval
       ↓
External service failure
       ↓
Error handling
       ↓
Log / return failure information
```

### Case 4: Successful Cache Refresh

When all required data is available and the refresh operation completes successfully, the function records the successful execution and returns the appropriate response.

## 🔄 Overall Workflow

```text
Trigger
   ↓
Validate required information
   ↓
Retrieve required data
   ↓
Process data
   ↓
Refresh Cache
   ↓
Success / Error Handling
```

## 🛠️ Technologies Used

* **Python**
* **Azure Functions**
* **MongoDB / PyMongo**
* **Requests**

## 🎯 Key Contribution

* Developed a **Python-based cache refresh function** during the MyPlacementBuddy internship.
* Implemented the logic required to refresh cached data programmatically.
* Added handling for different data availability and failure scenarios.
* Used logging and error handling to make function execution easier to monitor and troubleshoot.

## Contributors:
Tanisha Mathur 
Shyam 

## Mentors
Rajendra Sarpal
Vedant Singh
