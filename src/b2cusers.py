import httpx
from vendor.mggraph import connect_mggraph_application

class User:
    base_user_attributes = [
        "id",
        "givenName",
        "surname",
        "jobTitle",
        "mail",
        "creationType",
        "identities",
        "accountEnabled",
    ]
    extended_user_attributes = ["id", "ageGroup", "createdDateTime", "userType"]
    unwanted_attributes = [
        "emails",
        "jobTitle",
        "legalAgeGroupClassification",
        "newUser",
        "ObjectId",
    ]
    
    custom_user_attributes = []
    
    def __init__(
        self,
        app_id: str,
        secret: str,
        tenant_id: str,
        tenant_name: str,
        api_url: str = "https://graph.microsoft.com/v1.0",
    ) -> None:
        """
            Initializes all settings and creates a connection to the graph api

        Args:
            app_id (str): The application/ client id
            secret (str): The application secret
            tenant_id (str): The UUID of your Azure/Entra tenant
            tenant_name (str): The name of your Azure/Entra tenant eg. mytenant.onmicrosoft.com
            api_url (str, optional): The graph api url being used. Defaults to "https://graph.microsoft.com/v1.0".
        """

        self.tenant_name = tenant_name
        self.api_url = api_url
        
        self.graph_connection = connect_mggraph_application(app_id, secret, tenant_id, api_url)
        
        """
            Extension attributes are always in the format "extension_<b2c app id>_<extension name>"
            The b2c app id is that of the built in 
                `b2c-extensions-app. Do not modify. Used by AADB2C for storing user data.`
            app. 
            
            We create a mapping for easier processing.
        """

        # Fetch all the userflow_user_attributes
        extension_user_attributes = self.graph_connection.get(
            f"{self.api_url}/identity/userFlowAttributes"
        ).json()

        self.userflow_user_attributes = [
            extension["id"] for extension in extension_user_attributes["value"]
        ]

        # Prepare the userflow attribute mappings
        self.userflow_attribute_mapping = {}

        for extension in extension_user_attributes["value"]:
            if extension["userFlowAttributeType"] == "builtIn":
                self.userflow_attribute_mapping[extension["id"]] = extension["id"]
            else:
                extension_displayname = extension["displayName"].lower()
                extension_id = extension["id"]
                
                # Save to a list of only custom attributes and add it to the complete mapping file
                self.custom_user_attributes.append(extension_id)
                self.userflow_attribute_mapping[extension_displayname] = extension_id

        # Combine all user attributes
        self.all_user_attributes = (
            self.base_user_attributes
            + self.extended_user_attributes
            + self.userflow_user_attributes
        )
    
    def get_attributes(self) -> list:
        """
            == User attributes [CACHEABLE]

            We have a list of standard/extended  user attributes that we want in the object

            A overview of all attributes can be found here:
            https://learn.microsoft.com/en-us/azure/active-directory-b2c/user-profile-attributes

            Use the userflow_attribute_mapping variable when processing userflow attributes

        Returns:
            list: A list of all base, extended and userflow user attributes
        """

        # Combine all user attributes
        self.all_user_attributes = (
            self.base_user_attributes
            + self.extended_user_attributes
            + self.userflow_user_attributes
        )
        
        return self.all_user_attributes

    def search(self, email: str) -> dict:
        """
            Searches for a user by email address

        Args:
            email (str): email address to search for

        Returns:
            dict: user object if found, else empty object
        """
        
        import urllib.parse
        email = urllib.parse.quote(email)
        
        searchresult = self.graph_connection.get(
            f"{self.api_url}/users?$filter=(identities/any(i:i/issuer eq '{self.tenant_name}' and i/issuerAssignedId eq '{email}'))&$select=id,identities"
        ).json()

        return searchresult['value']

    def list(self, max: int = 0, include_attributes: list = []) -> dict:
        """
            This fetches a list of all users (paged per 1000 users)
            This does not contain all information, only the most basic information

            Users with `creationType = LocalAccount` are customers. (unless federated via social login)!
            This can be ascertained via the identities attribute

        Args:
            max (int, optional): Max number of accounts to fetch. If 0 return all accounts. Defaults to 999.
            include_attributes (list, optional): List of added attributes to fetch on top of the default attributes. Defaults to [].

        Returns:
            dict: Object containing a paginated list of users
        """

        attributes_to_fetch = set(self.base_user_attributes)
        
        for include_attribute in include_attributes:

            if include_attribute not in self.userflow_attribute_mapping:
                raise ValueError(f"{include_attribute} is not a known attribute. Only {','.join(self.userflow_attribute_mapping.keys())} are allowed")
            
            attributes_to_fetch.add(self.userflow_attribute_mapping[include_attribute])

        needed_attributes = ','.join(attributes_to_fetch)

        if(max == 0):
            all_customers = []
            
            fetch_customers = self.graph_connection.get(
                f"{self.api_url}/users",
                params={
                    "$select": needed_attributes,
                    "$top": 999,
                    "$filter": "creationType eq 'LocalAccount'"
                }
            ).json()
            
            all_customers.extend(fetch_customers['value'])
            
            while "@odata.nextLink" in fetch_customers:
                next_link = fetch_customers['@odata.nextLink']
                fetch_customers = self.graph_connection.get(next_link).json()
                all_customers.extend(fetch_customers['value'])
            
        elif(max <= 999):
            all_customers = self.graph_connection.get(
                f"{self.api_url}/users",
                params={
                    "$select": needed_attributes,
                    "$top": max,
                    "$filter": "creationType eq 'LocalAccount'"
                }
            ).json()
        else:
            raise Exception("max value should be between 0 and 999")

        # Fix fieldnames in returned list
        mapped_customers = []
        reversed_mapping = {v:k for k,v in self.userflow_attribute_mapping.items()}
        
        # Loop all records, if a field is an extension attribute map it and pop it from the dict
        for customer in all_customers:
            
            remapped_customer = {}
            
            for attribute,value in customer.items():
                if attribute in self.custom_user_attributes:
                    remapped_customer[reversed_mapping[attribute]] = value
                else:
                    remapped_customer[attribute] = value
            
            mapped_customers.append(remapped_customer)
        
        return mapped_customers

    def profile(self, userid: str, user_attributes: list = None) -> dict:
        """
            Fetch a full user profile

            One of the limitations of the graph api is that it only returns objects attributes that have a
            value set. In order to work around this problem we build our own object. We do this with the
            extension attributes that we selected earlier. We then fill in all data that we have.

            The rest is set to null

            In the example below we only fetch the userflow_user_attributes which are provided via the
            userflows since we don't have any more information from customers. Should we need more data for
            admin accounts etc we can use another value (or combination thereof) in the user_profile call

            - base_user_attributes
            - extended_user_attributes
            - userflow_user_attributes
            - all_user_attributes

            DisplayName is not used for customers in Azure B2C when using the built-in userflows, but can
            be set when manually creating a customer or updating a customer via the gui

        Args:
            userid (str): The user id/uuid/object id from Azure/Entra
            user_attributes (list): List of wanted user attributes. Defaults to all_user_attributes

        Returns:
            dict: Object containing all relevant user data
        """

        if user_attributes is None:
            user_attributes = self.all_user_attributes

        graph_user_profile = self.graph_connection.get(
            f"{self.api_url}/users/{userid}?$select={','.join(user_attributes)}"
        ).json()

        """ 
            First we do a full mapping with all extension attributes. Then we remove the attributes that 
            we do not want or that are irrelevant. 
            
            Lastly we fetch the user's email from the identities attribute and add this to the returned object
            in the email attribute.
            
            NOTE
            This process only works for customers that are in Azure B2C and are not federated from external
            identity providers. If this is the case we dont have an email in azure AD. The only way to get 
            the email is in the JWT after the user logs in (as intended). If you want to store the email
            you have to store it via put/patch to the /users endpoint
        """

        user_profile = {}

        for attribute, mapped_attribute in self.userflow_attribute_mapping.items():
            user_profile[attribute] = (
                graph_user_profile[mapped_attribute]
                if mapped_attribute in graph_user_profile
                else None
            )

        # Remove certain attributes from the object
        for attribute in self.unwanted_attributes:
            user_profile.pop(attribute, "")

        return user_profile

    def create(self, user: dict) -> dict:
        """
            Create a user

        Args:
            user (dict): User to be created.

        Returns:
            dict: A dictionairy containing the newly created user
        """

        # First map the known fields, extension attributes
        mapped_new_user = {}

        """
            We start with an input object like we provided before. Most fields are not required. Apart 
            from the main object, the following attributes are required:
            
            "passwordPolicies": "DisablePasswordExpiration"
            "accountEnabled": true
            
            Don't forget to provide a password:
            
            "passwordProfile" : {
                "password": "<password-value>",
                "forceChangePasswordNextSignIn": false
            }
            
            You will also need to provide the identities attribute. Make sure that this is a LIST of 
            objects.
            
            Setting a display name is not required but encouraged.
        """

        for attribute, mapped_attribute in self.userflow_attribute_mapping.items():
            if attribute in user:
                mapped_new_user[mapped_attribute] = user[attribute]

        mapped_new_user["displayName"] = user.get("displayName", f"{user.get("givenName")} {user.get("surname")}")
        mapped_new_user["mail"] = user["email"]
        mapped_new_user["accountEnabled"] = True
        mapped_new_user["passwordPolicies"] = "DisablePasswordExpiration"
        mapped_new_user["passwordProfile"] = {
            "password": user["password"],
            "forceChangePasswordNextSignIn": False,
        }
        mapped_new_user["identities"] = [
            {
                "issuer": self.tenant_name,
                "issuerAssignedId": user["email"],
                "signInType": "emailAddress",
            }
        ]

        create_user = self.graph_connection.post(
            f"{self.api_url}/users", json=mapped_new_user
        ).json()
        
        return create_user

    def update(self, userid: str, user: dict) -> bool:
        """
            Update a user

            Only send the fields that are required. All other fields remain unchanged.

            By default the graph api only returns a HTTP status code of 204 indicating the data has been updated.

            If you want to receive the full, updated object you need to add the header `Prefer: return=representation`.
            This is however bugged atm: https://github.com/microsoftgraph/msgraph-sdk-dotnet/issues/1682. Currently if
            you want the updated user account you need to perform a GET request.

        Args:
            userid (str): The user id/uuid/object id from Azure/Entra
            user (dict): User data to be changed.

        Returns:
            bool: True if the user was updated
        """

        # First map the known fields, extension attributes
        mapped_updated_customer = {}

        for attribute, mapped_attribute in self.userflow_attribute_mapping.items():
            if attribute in user:
                mapped_updated_customer[mapped_attribute] = user[attribute]

        update_user = self.graph_connection.patch(
            f"{self.api_url}/users/{userid}", json=mapped_updated_customer
        )

        return bool(update_user)

    def delete(self, userid: str) -> bool:
        """
            Delete a user

        Args:
            userid (str): The user id/uuid/object id from Azure/Entra

        Returns:
            bool: True if the user was deleted
        """

        delete_user = self.graph_connection.delete(f"{self.api_url}/users/{userid}")

        return bool(delete_user)

    def change_password(self, userid: str, password: str) -> bool:
        """
            Update a user's password

            
            Make sure to add the user administrator role for the app
            Azure Portal > Azure AD > Roles and Administrators> User Administrator > Click on Add Assignments
            https://learn.microsoft.com/en-us/graph/api/user-update?view=graph-rest-1.0&tabs=http#request-body
        Args:
            userid (str): The user id/uuid/object id from Azure/Entra
            password (str): The new password

        Returns:
            bool: True if the user's password was changed
        """

        user = {}
        user["passwordProfile"] = {
            "password": password,
            "forceChangePasswordNextSignIn": False,
        }
                
        update_password = self.graph_connection.patch(
            f"{self.api_url}/users/{userid}", json=user
        )

        return bool(update_password)
