import pyodbc
import uuid
import datetime

server = 'sqlserver.grupouniasselvi.local'
database = 'Bots'
username = 'bots-michaelscott'
password = 'Xunda33..'
driver= '{ODBC Driver 17 for SQL Server}'
cnxn = pyodbc.connect('DRIVER='+driver+';SERVER='+server+';PORT=1433;DATABASE='+database+';UID='+username+';PWD='+ password)
cursor = cnxn.cursor()

try:
    cnxn.autocommit = False
    request_id = str(uuid.uuid4())
    request_date = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    request_targ = "ASL-DHCP04" 
    request_expr = "Get-Process"
    request_requ = "rafael.gustmann@uniasselvi.com.br"
    cursor.execute(
        "INSERT INTO MichaelScott (RequestID, RequestDateTime, RequestTarget, RequestExpression, RequestRequester) VALUES (?, ?, ?, ?, ?)", 
        request_id, request_date, request_targ, request_expr, request_requ
        )
    cnxn.commit()
    #row = cursor.fetchone()
    #while row:
    #    print (str(row[0]) + " " + str(row[1]))
    #    row = cursor.fetchone()
except pyodbc.DatabaseError as err:
    print(err)
    cnxn.rollback()
else:
    cnxn.commit()
finally:
    cnxn.autocommit = True