import hishel
import httpx
import sqlite3
from datetime import datetime, timedelta
import webbrowser

# cache_storage = hishel.SQLiteStorage(connection=sqlite3.connect(".request-cache", timeout=5))
cache_storage = hishel.FileStorage(ttl=3600)

def connect_mggraph_devicecode(
        app_id: str,
        tenant_id: str,
        scopes: list,
        api_url: str = "https://graph.microsoft.com/v1.0"
    ) -> httpx.Client:
    
    """Connect to MS Graph using the device code flow. Makes use of delegated permissions

    Args:
        app_id (str): The Client/App id
        tenant_id (str): The Azure tenant id
        scopes (list): A list containing all scopes. Needs openid and profile if you need to fetch an ID token
        api_url (str, optional): The graph api url. Leave this to default unless you need the beta api. Defaults to "https://graph.microsoft.com/v1.0".

    Returns:
        hishel.CacheClient: Superset of Httpx Session/Client object ready to use
    """    
    
    # https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-device-code
    
    now = datetime.now()
    
    request_token = httpx.post(
        f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/devicecode",
        data={
            "scope": " ".join(scopes),
            "client_id": app_id
        },
    ).json()
    
    code_validity = datetime.strftime(now + timedelta(seconds=request_token['expires_in']), "%Y-%m-%d %H:%M:%S")
    
    device_code = request_token['device_code']

    print(f"Please enter the following code in your web browser:")
    print(f"{request_token['user_code']}")
    print(f"This code is valid for 15 minutes until {code_validity}")
    print(f"The browser will open automatically once you press enter.")
    input("Press Enter to open a browser window")
    
    webbrowser.open(request_token['verification_uri'])
    
    input("Press Enter once you have logged in with your device code")
    
    token = httpx.post(
    f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token",
    data={
        "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
        "client_id": app_id,
        "device_code": device_code
    },
    ).json()
    
    if "error" in token:
        if "7000218" in token['error_codes']:
            print("Public client flows not allowed. Please enable this in the appreg")
        else:
            print(token)
            
        exit()
    
    connection = hishel.CacheClient(
        storage=cache_storage,
        base_url=api_url,
        headers= {
            "Authorization": f"Bearer {token['access_token']}",
            # "ConsistencyLevel": "eventual",      # Needed for advanced queries
            # "Prefer": "return=representation",   # To get the object back with a PATCH
        },
        timeout=20.0
    )
    
    return connection

def connect_mggraph_application(
        app_id: str,
        secret: str,
        tenant_id: str,
        api_url: str = "https://graph.microsoft.com/v1.0"
    ) -> httpx.Client:

    """Connect to MS Graph using application secret. Makes use of application permissions

    Args:
        app_id (str): The Client/App id
        secret (str): The app secret
        tenant_id (str): The Azure tenant id
        api_url (str, optional): The graph api url. Leave this to default unless you need the beta api. Defaults to "https://graph.microsoft.com/v1.0".

    Returns:
        hishel.CacheClient: Superset of Httpx Session/Client object ready to use
    """ 
    
    token = httpx.post(
        f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token",
        data={
            "scope": "https://graph.microsoft.com/.default",
            "grant_type": "client_credentials",
            "client_id": app_id,
            "client_secret": secret,
        },
    ).json()
    
    # connection = httpx.Client(
        
    connection = hishel.CacheClient(
        storage=cache_storage,
        base_url=api_url,
        headers= {
            "Authorization": f"Bearer {token['access_token']}",
            # "ConsistencyLevel": "eventual",      # Needed for advanced queries
            # "Prefer": "return=representation",   # To get the object back with a PATCH
        },
        timeout=20.0
    )    
     
    return connection