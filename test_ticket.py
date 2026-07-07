#!/usr/bin/env python3
import paramiko

c = paramiko.SSHClient(); c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect('192.168.1.15', username='pablo', password='polo', timeout=10)
stdin, stdout, stderr = c.exec_command("curl -s -X POST http://localhost:5100/api/manual-exit -H 'Content-Type: application/json' -d '{\"plate\":\"761TBX\"}'")
print("EXIT:", stdout.read().decode().strip())
c.close()

c = paramiko.SSHClient(); c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect('192.168.1.15', username='pablo', password='polo', timeout=10)
stdin, stdout, stderr = c.exec_command("curl -s http://localhost:5100/api/ticket/1")
print("TICKET:", stdout.read().decode().strip())
c.close()
