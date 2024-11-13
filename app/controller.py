import asyncio
import aioping
from dotenv import dotenv_values
import logging
import os
from pprint import pprint as pp
import win32com.client as win32
from requests import get, post, Session, ConnectionError, HTTPError, Timeout
from time import sleep
from urllib3.exceptions import InsecureRequestWarning
from warnings import filterwarnings

# filter warnings about unsecure POST requests
filterwarnings("ignore", category=InsecureRequestWarning)


# set logger for program execution, show all messages from INFO level onwards
class CustomFormatter(logging.Formatter):
    grey = "\x1b[38;20m"
    green = "\x1b[32m"
    yellow = "\x1b[33;20m"
    red = "\x1b[31;20m"
    bold_red = "\x1b[31;1m"
    reset = "\x1b[0m"
    format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    FORMATS = {
        logging.DEBUG: grey + format + reset,
        logging.INFO: green + format + reset,
        logging.WARNING: yellow + format + reset,
        logging.ERROR: red + format + reset,
        logging.CRITICAL: bold_red + format + reset
    }

    def format(self, record):
        log_fmt = self.FORMATS.get(record.levelno)
        formatter = logging.Formatter(log_fmt)
        return formatter.format(record)


logger = logging.getLogger("Controller")
logger.setLevel(logging.DEBUG)
console = logging.StreamHandler()
console.setFormatter(CustomFormatter())
logger.addHandler(console)

# import personally identifiable information from environment variables
ENV_DIR = os.path.dirname(os.path.realpath(__file__)) + "/.env"
credentials = dotenv_values(ENV_DIR)
vManage_LDC_IP = credentials["VMANAGE_LDC_IP"]
vManage_HEIDI_IP = credentials["VMANAGE_HEIDI_IP"]
LDC_CONTROLLER_IP = credentials["LDC_CONTROLLER_IP"]
HEIDI_CONTROLLER_IP = credentials["HEIDI_CONTROLLER_IP"]
username = credentials["VMANAGE_USERNAME"]
password = credentials["VMANAGE_PASSWORD"]


def vmanage_authenticate(ip, username, password) -> Session:
    session = Session()
    vmanage_session_id = None
    vmanage_x_xsrf_token = None

    payload = {
        "j_username": username,
        "j_password": password
    }

    try:
        response = post(url=f"https://{ip}/j_security_check",
                        data=payload,
                        verify=False)
        if response.ok:
            cookies = response.headers["Set-Cookie"]
            vmanage_session_id = cookies.split(";")[0]
        else:
            logger.critical("vManage Authentication: Failed to retrieve session ID")
            exit()

        response = get(url=f"https://{ip}/dataservice/client/token",
                       headers={"Cookie": vmanage_session_id},
                       verify=False)
        if response.ok:
            vmanage_x_xsrf_token = response.text
        else:
            logger.critical("vManage Authentication: Failed to retrieve session token")
            exit()
    except:
        logger.critical("vManage Authentication: Failed to make a POST request to vManage API. Check URL and "
                        "Credentials")
        exit()

    if vmanage_x_xsrf_token is not None:
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'Cookie': vmanage_session_id,
            'X-XSRF-TOKEN': vmanage_x_xsrf_token
        }
    else:
        headers = {
            'Content-Type': "application/json",
            'Cookie': vmanage_session_id
        }

    session.headers.update(headers)
    logger.info("vManage Authentication: Authentication Successful")

    return session


def instantiate_vmanage_controllers() -> dict:
    response = None
    session = vmanage_authenticate(ip=vManage_LDC_IP,
                                   username=username,
                                   password=password)
    try:
        response = session.get(
            url=f"https://{vManage_LDC_IP}/dataservice/disasterrecovery/clusterInfo",
            data={},
            verify=False
        )

        if response.ok:
            logger.info(f"vManage Controller Cluster: Information Retrieval Successful")
            return response.json()["clusterInfo"]
        else:
            response.raise_for_status()

    except HTTPError:
        if response.status_code == 400:
            logger.critical(f"vManage Controller Cluster: 400: Bad request made, check URL/malformed syntax/illegal "
                            f"characters")
            exit()
        elif response.status_code == 403:
            logger.critical(f"vManage Controller Cluster: 403: Insufficient permissions, refresh session ID and "
                            f"client token")
            exit()
        elif response.status_code == 500:
            logger.critical(
                f"vManage Controller Cluster: 500: Internal server error, check if API method is still valid")
            exit()

    except ConnectionError:
        logger.critical(f"vManage Controller Cluster:: Connection error, check connection to the internal network")
        exit()

    except Timeout:
        logger.critical(f"vManage Controller Cluster:: Timeout error, re-authenticate session")
        exit()


def send_disaster_email():
    outlook = win32.Dispatch('outlook.application')

    recipients = ["rodev@cisco.com"]  # Add email addresses
    # recipients = ["rodev@cisco.com", "xuyhan@cisco.com", "haztan@cisco.com", "jopoh@cisco.com", "booong@cisco.com",
    #               "deschia@cisco.com", "kimloo@cisco.com", "dtok@cisco.com", "wagoh@cisco.com", "benjtan@cisco.com",
    #               "charilim@cisco.com", "jiboh@cisco.com"]
    cc_list = []  # Add CC emails
    bcc_list = []  # Add BCC emails
    subject = "Enterprise SD-WAN vManage Clusters are Unreachable"
    body = """
    Dear Network Operator,

    Your vManage clusters are unreachable, and are likely to be down. Head down to the data centers.

    Best regards,
    Mr. Inconvenient Truth
    Facility Manager
    Network Gurus Inc.
    """
    executive_email = "rodev@cisco.com"  # The email from which the messages should appear to be sent

    for recipient in recipients:
        mail = outlook.CreateItem(0)
        mail.To = recipient
        if cc_list:
            mail.CC = "; ".join(cc_list)
        if bcc_list:
            mail.BCC = "; ".join(bcc_list)
        mail.Subject = subject
        mail.Body = body
        # Set the sending account
        mail._oleobj_.Invoke(*(64209, 0, 8, 0, outlook.Session.Accounts.Item(executive_email)))

        mail.Send()
        sleep(1)  # Sleep for a second to avoid sending too many emails too quickly


class vManage:
    def __init__(self, hostname, ip, is_primary_vmanage, username, password):
        self.hostname = hostname
        self.ip = ip
        self.is_primary_vmanage = is_primary_vmanage
        self.username = username
        self.password = password
        self.session = self.authenticate()

    def authenticate(self) -> Session:
        return vmanage_authenticate(self.ip, self.username, self.password)

    def pause_disaster_recovery_telemetry(self) -> None:
        response = None
        try:
            response = self.session.post(url=f"https://{self.ip}/dataservice/disasterrecovery/pause",
                                         data={},
                                         verify=False)
            if response.ok:
                logger.info(f"{self.hostname} Pause DR Telemetry: Pause Successful")
            else:
                logger.info(f"{self.hostname} Pause DR Telemetry: Pause Unsuccessful")
                response.raise_for_status()

        except HTTPError:
            if response.status_code == 400:
                logger.critical(f"{self.hostname} Pause DR Telemetry: 400: Bad request made, check URL/malformed "
                                f"syntax/illegal characters")
                exit()
            elif response.status_code == 403:
                logger.critical(
                    f"{self.hostname} Pause DR Telemetry: 403: Insufficient permissions, refresh session ID "
                    f"and client token")
                exit()
            elif response.status_code == 500:
                logger.critical(
                    f"{self.hostname} Pause DR Telemetry: 500: Internal server error, check if API method is "
                    f"still valid")
                exit()

        except ConnectionError:
            logger.critical(f"{self.hostname} Pause DR Telemetry: Connection error, check connection to the internal "
                            f"network")
            exit()

        except Timeout:
            logger.critical(f"{self.hostname} Pause DR Telemetry: Timeout error, re-authenticate session")
            exit()

    def unpause_disaster_recovery_telemetry(self) -> None:
        response = None
        try:
            response = self.session.post(url=f"https://{self.ip}/dataservice/disasterrecovery/unpause",
                                         data={},
                                         verify=False)
            if response.ok:
                logger.info(f"{self.hostname} Unpause DR Telemetry: Unpause Successful")
            else:
                logger.info(f"{self.hostname} Unpause DR Telemetry: Unpause Unsuccessful")
                response.raise_for_status()

        except HTTPError:
            if response.status_code == 400:
                logger.critical(f"{self.hostname} Unpause DR Telemetry: 400: Bad request made, check URL/malformed "
                                f"syntax/illegal characters")
                exit()
            elif response.status_code == 403:
                logger.critical(
                    f"{self.hostname} Unpause DR Telemetry: 403: Insufficient permissions, refresh session ID "
                    f"and client token")
                exit()
            elif response.status_code == 500:
                logger.critical(
                    f"{self.hostname} Unpause DR Telemetry: 500: Internal server error, check if API method is "
                    f"still valid")
                exit()

        except ConnectionError:
            logger.critical(f"{self.hostname} Unpause DR Telemetry: Connection error, check connection to the internal "
                            f"network")
            exit()

        except Timeout:
            logger.critical(f"{self.hostname} Unpause DR Telemetry: Timeout error, re-authenticate session")
            exit()

    def make_primary_cluster(self) -> bool:
        response = None
        try:
            response = self.session.post(url=f"https://{self.ip}/dataservice/disasterrecovery/activate",
                                         data={},
                                         verify=False)
            if response.ok:
                logger.info(f"{self.hostname} Primary Cluster: Activation Successful")
                self.is_primary_vmanage = True
                return True
            else:
                logger.info(f"{self.hostname} Primary Cluster: Activation Unsucessful")
                response.raise_for_status()

        except HTTPError:
            if response.status_code == 400:
                logger.critical(f"{self.hostname} Primary Cluster: 400: Bad request made, check URL/malformed "
                                f"syntax/illegal characters")
                exit()
            elif response.status_code == 403:
                logger.critical(f"{self.hostname} Primary Cluster: 403: Insufficient permissions, refresh session ID "
                                f"and client token")
                exit()
            elif response.status_code == 500:
                logger.critical(f"{self.hostname} Primary Cluster: 500: Internal server error, check if API method is "
                                f"still valid")
                exit()

        except ConnectionError:
            logger.critical(f"{self.hostname} Primary Cluster: Connection error, check connection to the internal "
                            f"network")
            exit()

        except Timeout:
            logger.critical(f"{self.hostname} Primary Cluster: Timeout error, re-authenticate session")
            exit()

        return False


class Controller:
    def __init__(self, vmanage_one, vmanage_two):
        self.vmanage_one = vmanage_one
        self.vmanage_two = vmanage_two
        self.primary_vmanage = vmanage_one if vmanage_one.is_primary_vmanage else vmanage_two

    async def ping_server(self, controller_ip, timeout=1) -> bool:
        try:
            await aioping.ping(dest_addr=controller_ip, timeout=timeout)  # timeout is in seconds
            return True
        except TimeoutError:
            return False

    async def continuous_ping(self, failure_threshold=5) -> None:
        both_already_unreachable = False
        consecutive_failures = 0

        while True:
            success_vmanage_one = await self.ping_server(LDC_CONTROLLER_IP)
            success_vmanage_two = await self.ping_server(HEIDI_CONTROLLER_IP)

            # both vmanage clusters are reachable
            if success_vmanage_one and success_vmanage_two:
                both_already_unreachable = False
                consecutive_failures = 0  # reset on success
                logger.info(f"{self.vmanage_one.hostname} and {self.vmanage_two.hostname} reachable")
            else:
                consecutive_failures += 1

                # both vmanage clusters are unreachable
                if not success_vmanage_one and not success_vmanage_two:
                    if both_already_unreachable:
                        logger.error(f"Failed to ping {self.vmanage_one.hostname} and {self.vmanage_two.hostname}. ")
                        consecutive_failures = 0  # reset counter since it is known that both are already unreachable
                        continue
                    logger.warning(f"Failed to ping {self.vmanage_one.hostname} and {self.vmanage_two.hostname}. "
                                   f"Failure count: {consecutive_failures}")
                    if consecutive_failures >= failure_threshold:
                        logger.error(f"Consecutive failure threshold of {failure_threshold} reached. Both vManage "
                                     f"clusters unreachable. Alert notification sent...")
                        both_already_unreachable = True

                        # alert notification sent to a message gateway since both vManage clusters are unreachable
                        send_disaster_email()

                # one vmanage cluster is reachable, the other is unreachable
                else:
                    both_already_unreachable = False
                    logger.warning(
                        f"Failed to ping {self.vmanage_one.hostname if not success_vmanage_one else self.vmanage_two.hostname}. ")

                    if success_vmanage_one and not success_vmanage_two:
                        if self.primary_vmanage == self.vmanage_one:
                            consecutive_failures = 0  # reset counter since current primary vmanage is reachable
                            logger.warning(f"Primary vManage is {self.primary_vmanage.hostname}")
                        else:
                            logger.warning(
                                f"Ping failure count: {consecutive_failures}. Primary vManage is {self.primary_vmanage.hostname}")
                            if consecutive_failures >= failure_threshold and self.vmanage_two.is_primary_vmanage:
                                logger.warning(
                                    f"Consecutive failure threshold of {failure_threshold} reached. Swinging "
                                    f"vManage cluster from {self.vmanage_two.hostname} to {self.vmanage_one.hostname}")

                                # pause telemetry before initiating DR swing
                                logger.info("Commencing pausing of DR telemetry...")
                                self.primary_vmanage.pause_disaster_recovery_telemetry()

                                # swing DR cluster
                                result = self.vmanage_one.make_primary_cluster()
                                if result:
                                    self.vmanage_one.is_primary_vmanage = True
                                    self.vmanage_two.is_primary_vmanage = False
                                    self.primary_vmanage = self.vmanage_one
                                    consecutive_failures = 0  # reset after disaster recovery swing
                                    logger.info(f"={self.vmanage_one.hostname} is primary vManage cluster. "
                                                f"{self.vmanage_two.hostname} is secondary vManage cluster.")

                                    # resume telemetry after DR swing
                                    self.primary_vmanage.unpause_disaster_recovery_telemetry()

                    elif not success_vmanage_one and success_vmanage_two:
                        if self.primary_vmanage == self.vmanage_two:
                            consecutive_failures = 0  # reset counter since current primary vmanage is reachable
                            logger.warning(f"Primary vManage is {self.primary_vmanage.hostname}")
                        else:
                            logger.warning(
                                f"Ping failure count: {consecutive_failures}. Primary vManage is {self.primary_vmanage.hostname}")
                            if consecutive_failures >= failure_threshold and self.vmanage_one.is_primary_vmanage:
                                logger.warning(
                                    f"Consecutive failure threshold of {failure_threshold} reached. Swinging "
                                    f"vManage cluster from {self.vmanage_one.hostname} to {self.vmanage_two.hostname}")

                                # pause telemetry before initiating DR swing
                                logger.info("Commencing pausing of DR telemetry...")
                                self.primary_vmanage.pause_disaster_recovery_telemetry()

                                # swing DR cluster
                                result = self.vmanage_two.make_primary_cluster()
                                if result:
                                    self.vmanage_two.is_primary_vmanage = True
                                    self.vmanage_one.is_primary_vmanage = False
                                    self.primary_vmanage = self.vmanage_two
                                    consecutive_failures = 0  # reset after disaster recovery swing
                                    logger.info(f"={self.vmanage_two.hostname} is primary vManage cluster. "
                                                f"{self.vmanage_one.hostname} is secondary vManage cluster.")

                                    # resume telemetry after DR swing
                                    self.primary_vmanage.unpause_disaster_recovery_telemetry()

            await asyncio.sleep(1)  # wait a second before pinging again


async def main():
    # vmanage_cluster_info = instantiate_vmanage_controllers()
    controller = Controller(
        vmanage_one=vManage(
            # hostname=vmanage_cluster_info["primary"][0]["host-name"],
            hostname="vManage_LDC",
            ip=vManage_LDC_IP,
            is_primary_vmanage=True,
            username=username,
            password=password
        ),
        vmanage_two=vManage(
            # hostname=vmanage_cluster_info["secondary"][0]["host-name"],
            hostname="vManage_HEIDI",
            ip=vManage_HEIDI_IP,
            is_primary_vmanage=False,
            username=username,
            password=password
        )
    )

    logger.info(f"{controller.vmanage_one.hostname} and {controller.vmanage_two.hostname} instantiated successfully")
    await controller.continuous_ping()


if __name__ == '__main__':
    asyncio.run(main())
