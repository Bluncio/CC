import random # This is random bullshit
import logging
import subprocess
import sys
import os
import re
import time
import concurrent.futures
import discord
from discord.ext import commands, tasks
import docker
import asyncio
from discord import app_commands

TOKEN = '' # TOKEN HERE
RAM_LIMIT = '20g'
SERVER_LIMIT = 10
database_file = 'database.txt'

intents = discord.Intents.default()
intents.messages = False
intents.message_content = False

bot = commands.Bot(command_prefix='/', intents=intents)
client = docker.from_env()

# port gen forward module < i forgot this shit in the start
def generate_random_port(): 
    return random.randint(1025, 65535)

def add_to_database(user, container_name, ssh_command):
    with open(database_file, 'a') as f:
        f.write(f"{user}|{container_name}|{ssh_command}\n")

def remove_from_database(ssh_command):
    if not os.path.exists(database_file):
        return
    with open(database_file, 'r') as f:
        lines = f.readlines()
    with open(database_file, 'w') as f:
        for line in lines:
            if ssh_command not in line:
                f.write(line)

async def capture_ssh_session_line(process):
    while True:
        output = await process.stdout.readline()
        if not output:
            break
        output = output.decode('utf-8').strip()
        if "sesja ssh:" in output:
            return output.split("sesja ssh:")[1].strip()
    return None

def get_ssh_command_from_database(container_id):
    if not os.path.exists(database_file):
        return None
    with open(database_file, 'r') as f:
        for line in f:
            if container_id in line:
                return line.split('|')[2]
    return None

def get_user_servers(user):
    if not os.path.exists(database_file):
        return []
    servers = []
    with open(database_file, 'r') as f:
        for line in f:
            if line.startswith(user):
                servers.append(line.strip())
    return servers

def count_user_servers(user):
    return len(get_user_servers(user))

def get_container_id_from_database(user):
    servers = get_user_servers(user)
    if servers:
        return servers[0].split('|')[1]
    return None

@bot.event
async def on_ready():
    change_status.start()
    print(f'Bot jest gotowy. Zalogowano jako {bot.user}')
    await bot.tree.sync()

@tasks.loop(seconds=5)
async def change_status():
    try:
        if os.path.exists(database_file):
            with open(database_file, 'r') as f:
                lines = f.readlines()
                instance_count = len(lines)
        else:
            instance_count = 0

        status = f"z {instance_count} Instancje w chmurze"
        await bot.change_presence(activity=discord.Game(name=status))
    except Exception as e:
        print(f"Nie udało się zaktualizować statusu: {e}")

async def regen_ssh_command(interaction: discord.Interaction, container_name: str):
    user = str(interaction.user)
    container_id = get_container_id_from_database(user, container_name)

    if not container_id:
        await interaction.response.send_message(embed=discord.Embed(description="Nie znaleziono żadnej aktywnej instancji dla Twojego użytkownika.", color=0xff0000))
        return

    try:
        exec_cmd = await asyncio.create_subprocess_exec("docker", "exec", container_id, "tmate", "-F",
                                                        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    except subprocess.CalledProcessError as e:
        await interaction.response.send_message(embed=discord.Embed(description=f"Błąd podczas wykonywania tmate w kontenerze Docker: {e}", color=0xff0000))
        return

    ssh_session_line = await capture_ssh_session_line(exec_cmd)
    if ssh_session_line:
        await interaction.user.send(embed=discord.Embed(description=f"### Nowe polecenie sesji SSH: ```{ssh_session_line}```", color=0x00ff00))
        await interaction.response.send_message(embed=discord.Embed(description="Wygenerowano nową sesję SSH. Sprawdź swoje DM, aby uzyskać szczegóły.", color=0x00ff00))
    else:
        await interaction.response.send_message(embed=discord.Embed(description="Nie udało się wygenerować nowej sesji SSH.", color=0xff0000))

async def start_server(interaction: discord.Interaction, container_name: str):
    user = str(interaction.user)
    container_id = get_container_id_from_database(user, container_name)

    if not container_id:
        await interaction.response.send_message(embed=discord.Embed(description="Nie znaleziono wystąpienia dla Twojego użytkownika.", color=0xff0000))
        return

    try:
        subprocess.run(["docker", "start", container_id], check=True)
        exec_cmd = await asyncio.create_subprocess_exec("docker", "exec", container_id, "tmate", "-F",
                                                        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        ssh_session_line = await capture_ssh_session_line(exec_cmd)
        if ssh_session_line:
            await interaction.user.send(embed=discord.Embed(description=f"### Uruchomiono wystąpienie\nPolecenie sesji SSH: ```{ssh_session_line}```", color=0x00ff00))
            await interaction.response.send_message(embed=discord.Embed(description="Instancja uruchomiona pomyślnie. Sprawdź swoje DM, aby uzyskać szczegóły.", color=0x00ff00))
        else:
            await interaction.response.send_message(embed=discord.Embed(description="Instancja została uruchomiona, ale nie udało się nawiązać połączenia z sesją SSH.", color=0xff0000))
    except subprocess.CalledProcessError as e:
        await interaction.response.send_message(embed=discord.Embed(description=f"Błąd podczas uruchamiania instancji: {e}", color=0xff0000))

async def stop_server(interaction: discord.Interaction, container_name: str):
    user = str(interaction.user)
    container_id = get_container_id_from_database(user, container_name)

    if not container_id:
        await interaction.response.send_message(embed=discord.Embed(description="Nie znaleziono wystąpienia dla Twojego użytkownika.", color=0xff0000))
        return

    try:
        subprocess.run(["docker", "stop", container_id], check=True)
        await interaction.response.send_message(embed=discord.Embed(description="Instancja została pomyślnie zatrzymana.", color=0x00ff00))
    except subprocess.CalledProcessError as e:
        await interaction.response.send_message(embed=discord.Embed(description=f"Błąd podczas zatrzymywania instancji: {e}", color=0xff0000))

async def restart_server(interaction: discord.Interaction, container_name: str):
    user = str(interaction.user)
    container_id = get_container_id_from_database(user, container_name)

    if not container_id:
        await interaction.response.send_message(embed=discord.Embed(description="Nie znaleziono wystąpienia dla Twojego użytkownika.", color=0xff0000))
        return

    try:
        subprocess.run(["docker", "restart", container_id], check=True)
        exec_cmd = await asyncio.create_subprocess_exec("docker", "exec", container_id, "tmate", "-F",
                                                        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        ssh_session_line = await capture_ssh_session_line(exec_cmd)
        if ssh_session_line:
            await interaction.user.send(embed=discord.Embed(description=f"### Instancja uruchomiona ponownie\nPolecenie sesji SSH: ```{ssh_session_line}```\nOS: Ubuntu 22.04", color=0x00ff00))
            await interaction.response.send_message(embed=discord.Embed(description="Instancja została pomyślnie ponownie uruchomiona. Sprawdź swoje DM, aby uzyskać szczegóły.", color=0x00ff00))
        else:
            await interaction.response.send_message(embed=discord.Embed(description="Instancja została ponownie uruchomiona, ale nie doszło do awarii z sesją SSH.", color=0xff0000))
    except subprocess.CalledProcessError as e:
        await interaction.response.send_message(embed=discord.Embed(description=f"Błąd podczas ponownego uruchamiania instancji:{e}", color=0xff0000))

def get_container_id_from_database(user, container_name):
    if not os.path.exists(database_file):
        return None
    with open(database_file, 'r') as f:
        for line in f:
            if line.startswith(user) and container_name in line:
                return line.split('|')[1]
    return None

async def execute_command(command):
    process = await asyncio.create_subprocess_shell(
        command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await process.communicate()
    return stdout.decode(), stderr.decode()

PUBLIC_IP = '138.68.79.95'

async def capture_output(process, keyword):
    while True:
        output = await process.stdout.readline()
        if not output:
            break
        output = output.decode('utf-8').strip()
        if keyword in output:
            return output
    return None

@bot.tree.command(name="port-add", description="Dodaje regułę przekierowania portów")
@app_commands.describe(container_name="Nazwa kontenera", container_port="Port w kontenerze")
async def port_add(interaction: discord.Interaction, container_name: str, container_port: int):
    await interaction.response.send_message(embed=discord.Embed(description="Konfigurowanie przekierowania portów. To może chwilę potrwać...", color=0x00ff00))

    public_port = generate_random_port()

    # Set up port forwarding inside the container
    command = f"ssh -o StrictHostKeyChecking=no -R {public_port}:localhost:{container_port} serveo.net -N -f"

    try:
        # Run the command in the background using Docker exec
        await asyncio.create_subprocess_exec(
            "docker", "exec", container_name, "bash", "-c", command,
            stdout=asyncio.subprocess.DEVNULL,  # No need to capture output
            stderr=asyncio.subprocess.DEVNULL  # No need to capture errors
        )

        # Respond immediately with the port and public IP
        await interaction.followup.send(embed=discord.Embed(description=f"Port został pomyślnie dodany. Twoja usługa jest hostowana na{PUBLIC_IP}:{public_port}.", color=0x00ff00))

    except Exception as e:
        await interaction.followup.send(embed=discord.Embed(description=f"An unexpected error occurred: {e}", color=0xff0000))

@bot.tree.command(name="port-http", description="Przekieruj ruch HTTP do swojego kontenera")
@app_commands.describe(container_name="Nazwa Twojego kontenera", container_port="Port wewnątrz kontenera do przesyłania dalej")
async def port_forward_website(interaction: discord.Interaction, container_name: str, container_port: int):
    try:
        exec_cmd = await asyncio.create_subprocess_exec(
            "docker", "exec", container_name, "ssh", "-o StrictHostKeyChecking=no", "-R", f"80:localhost:{container_port}", "serveo.net",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        url_line = await capture_output(exec_cmd, "Przekierowywanie ruchu HTTP z")
        if url_line:
            url = url_line.split(" ")[-1]
            await interaction.response.send_message(embed=discord.Embed(description=f"Strona internetowa została pomyślnie przekazana. Twoja strona internetowa jest dostępna pod adresem {url}.", color=0x00ff00))
        else:
            await interaction.response.send_message(embed=discord.Embed(description="Nie udało się przechwycić adresu URL przekierowania.", color=0xff0000))
    except subprocess.CalledProcessError as e:
        await interaction.response.send_message(embed=discord.Embed(description=f"Wystąpił błąd podczas przekierowywania witryny: {e}", color=0xff0000))

async def create_server_task(interaction):
    await interaction.response.send_message(embed=discord.Embed(description="Tworzenie instancji. Zajmie to kilka sekund.", color=0x00ff00))
    user = str(interaction.user)
    if count_user_servers(user) >= SERVER_LIMIT:
        await interaction.followup.send(embed=discord.Embed(description="```Błąd: osiągnięto limit instancji```", color=0xff0000))
        return

    image = "ubuntu-22.04-with-tmate"
    
    try:
        container_id = subprocess.check_output([
            "docker", "run", "-itd", "--privileged", "--cap-add=ALL", image
        ]).strip().decode('utf-8')
    except subprocess.CalledProcessError as e:
        await interaction.followup.send(embed=discord.Embed(description=f"Błąd podczas tworzenia kontenera Docker: {e}", color=0xff0000))
        return

    try:
        exec_cmd = await asyncio.create_subprocess_exec("docker", "exec", container_id, "tmate", "-F",
                                                        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    except subprocess.CalledProcessError as e:
        await interaction.followup.send(embed=discord.Embed(description=f"Błąd podczas wykonywania tmate w kontenerze Docker: {e}", color=0xff0000))
        subprocess.run(["docker", "kill", container_id])
        subprocess.run(["docker", "rm", container_id])
        return

    ssh_session_line = await capture_ssh_session_line(exec_cmd)
    if ssh_session_line:
        await interaction.user.send(embed=discord.Embed(description=f"### SPomyślnie utworzono sesję instancji\nSSH. Polecenie: ```{ssh_session_line}```\nOS: Ubuntu 22.04", color=0x00ff00))
        add_to_database(user, container_id, ssh_session_line)
        await interaction.followup.send(embed=discord.Embed(description="Instancja utworzona pomyślnie. Sprawdź swoje DM, aby uzyskać szczegóły.", color=0x00ff00))
    else:
        await interaction.followup.send(embed=discord.Embed(description="Coś poszło nie tak lub Instancja trwa dłużej niż oczekiwano. Jeśli ten problem będzie się powtarzał, skontaktuj się z pomocą techniczną.", color=0xff0000))
        subprocess.run(["docker", "kill", container_id])
        subprocess.run(["docker", "rm", container_id])

async def create_server_task_debian(interaction):
    await interaction.response.send_message(embed=discord.Embed(description="Tworzenie instancji. Zajmie to kilka sekund.", color=0x00ff00))
    user = str(interaction.user)
    if count_user_servers(user) >= SERVER_LIMIT:
        await interaction.followup.send(embed=discord.Embed(description="```Błąd: osiągnięto limit instancji```", color=0xff0000))
        return

    image = "debian-with-tmate"
    
    try:
        container_id = subprocess.check_output([
            "docker", "run", "-itd", "--privileged", "--cap-add=ALL", image
        ]).strip().decode('utf-8')
    except subprocess.CalledProcessError as e:
        await interaction.followup.send(embed=discord.Embed(description=f"Błąd podczas tworzenia kontenera Docker: {e}", color=0xff0000))
        return

    try:
        exec_cmd = await asyncio.create_subprocess_exec("docker", "exec", container_id, "tmate", "-F",
                                                        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    except subprocess.CalledProcessError as e:
        await interaction.followup.send(embed=discord.Embed(description=f"Błąd podczas wykonywania tmate w kontenerze Docker: {e}", color=0xff0000))
        subprocess.run(["docker", "kill", container_id])
        subprocess.run(["docker", "rm", container_id])
        return

    ssh_session_line = await capture_ssh_session_line(exec_cmd)
    if ssh_session_line:
        await interaction.user.send(embed=discord.Embed(description=f"### Successfully created Instance\nSSH Session Command: ```{ssh_session_line}```\nOS: Debian", color=0x00ff00))
        add_to_database(user, container_id, ssh_session_line)
        await interaction.followup.send(embed=discord.Embed(description="Instancja utworzona pomyślnie. Sprawdź swoje DM, aby uzyskać szczegóły.", color=0x00ff00))
    else:
        await interaction.followup.send(embed=discord.Embed(description="Coś poszło nie tak lub Instancja trwa dłużej niż oczekiwano. Jeśli ten problem będzie się powtarzał, skontaktuj się z pomocą techniczną.", color=0xff0000))
        subprocess.run(["docker", "kill", container_id])
        subprocess.run(["docker", "rm", container_id])

@bot.tree.command(name="Stwórz-Ubuntu", description="Tworzy nową instancję z Ubuntu 22.04")
async def deploy_ubuntu(interaction: discord.Interaction):
    await create_server_task(interaction)

@bot.tree.command(name="Stwórz-debian", description="Tworzy nową instancję z Debianem 12")
async def deploy_ubuntu(interaction: discord.Interaction):
    await create_server_task_debian(interaction)

@bot.tree.command(name="regeneruj-ssh", description="Generuje nową sesję SSH dla Twojej instancji")
@app_commands.describe(container_name="Nazwa/polecenie ssh Twojej instancji")
async def regen_ssh(interaction: discord.Interaction, container_name: str):
    await regen_ssh_command(interaction, container_name)

@bot.tree.command(name="start", description="Uruchamia Twoją instancję")
@app_commands.describe(container_name="Nazwa/polecenie ssh Twojej instancji")
async def start(interaction: discord.Interaction, container_name: str):
    await start_server(interaction, container_name)

@bot.tree.command(name="stop", description="Zatrzymuje Twoją instancję")
@app_commands.describe(container_name="Nazwa/polecenie ssh Twojej instancji")
async def stop(interaction: discord.Interaction, container_name: str):
    await stop_server(interaction, container_name)

@bot.tree.command(name="restart", description="„Restartuje Twoją instancję")
@app_commands.describe(container_name="Nazwa/polecenie ssh Twojej instancji")
async def restart(interaction: discord.Interaction, container_name: str):
    await restart_server(interaction, container_name)

@bot.tree.command(name="ping", description="Sprawdź opóźnienie bota.")
async def ping(interaction: discord.Interaction):
    latency = round(bot.latency * 1000)
    embed = discord.Embed(
        title="🏓 Pong!",
        description=f"Latency: {latency}ms",
        color=discord.Color.green()
    )
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="lista", description="Wyświetla wszystkie Twoje wystąpienia")
async def list_servers(interaction: discord.Interaction):
    user = str(interaction.user)
    servers = get_user_servers(user)
    if servers:
        embed = discord.Embed(title="Twoje instancje", color=0x00ff00)
        for server in servers:
            _, container_name, _ = server.split('|')
            embed.add_field(name=container_name, value="Opis: 62 GB Pamięci RAM i 6 rdzeni 327 GB Pamięciu Dysku. ", inline=False)
        await interaction.response.send_message(embed=embed)
    else:
        await interaction.response.send_message(embed=discord.Embed(description="Nie masz żadnych serwerów.", color=0xff0000))

@bot.tree.command(name="Ususwanie-Serwera", description="Stałe usuwanie serwera")
@app_commands.describe(container_name="Nazwa/polecenie ssh Twojej instancji")
async def remove_server(interaction: discord.Interaction, container_name: str):
    user = str(interaction.user)
    container_id = get_container_id_from_database(user, container_name)

    if not container_id:
        await interaction.response.send_message(embed=discord.Embed(description="Nie znaleziono wystąpienia dla Twojego użytkownika o takiej nazwie.", color=0xff0000))
        return

    try:
        subprocess.run(["docker", "stop", container_id], check=True)
        subprocess.run(["docker", "rm", container_id], check=True)
        
        remove_from_database(container_id)
        
        await interaction.response.send_message(embed=discord.Embed(description=f"Przykład '{container_name}' usunięto pomyślnie.", color=0x00ff00))
    except subprocess.CalledProcessError as e:
        await interaction.response.send_message(embed=discord.Embed(description=f"Błąd podczas usuwania instancji: {e}", color=0xff0000))

@bot.tree.command(name="Pomoc-Komendy", description="Wyświetla komunikat pomocy")
async def help_command(interaction: discord.Interaction):
    embed = discord.Embed(title="Help", color=0x00ff00)
    embed.add_field(name="/Stwórz-Ubuntu", value="Tworzy nową instancję z Ubuntu 22.04.", inline=False)
    embed.add_field(name="/Stwórz-debian", value="Tworzy nową instancję z systemem Debian 12.", inline=False)
    embed.add_field(name="/Ususwanie-Serwera <ssh_command/Name>", value="Usuwa serwer", inline=False)
    embed.add_field(name="/start <ssh_command/Name>", value="Uruchom serwer.", inline=False)
    embed.add_field(name="/stop <ssh_command/Name>", value="Zatrzymaj serwer.", inline=False)
    embed.add_field(name="/regeneruj-ssh <ssh_command/Name>", value="Regeneruje dane uwierzytelniające SSH", inline=False)
    embed.add_field(name="/restart <polecenie_ssh/nazwa>", value="Zatrzymaj serwer.", inline=False)
    embed.add_field(name="/Lista", value="Wypisz wszystkie swoje serwery", inline=False)
    embed.add_field(name="/ping", value="Sprawdź opóźnienie bota.", inline=False)
    embed.add_field(name="/port-http", value="Przekieruj witrynę http.", inline=False)
    embed.add_field(name="/port-add", value="Przekieruj port.", inline=False)
    await interaction.response.send_message(embed=embed)

bot.run(TOKEN)
