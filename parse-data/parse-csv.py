import csv
import sys
import re

file = 'data/us-500.csv'

if len(sys.argv) == 3:
	state = sys.argv[1].upper()
	name = sys.argv[2]
elif len(sys.argv) == 2:
	state = sys.argv[1].upper()
	name = ''	
else:
	print("you need to enter a state abbreviation and an optional name!")
	exit()


states = [ 'AK', 'AL', 'AR', 'AZ', 'CA', 'CO', 'CT', 'DC', 'DE', 'FL', 'GA',
           'HI', 'IA', 'ID', 'IL', 'IN', 'KS', 'KY', 'LA', 'MA', 'MD', 'ME',
           'MI', 'MN', 'MO', 'MS', 'MT', 'NC', 'ND', 'NE', 'NH', 'NJ', 'NM',
           'NV', 'NY', 'OH', 'OK', 'OR', 'PA', 'RI', 'SC', 'SD', 'TN', 'TX',
           'UT', 'VA', 'VT', 'WA', 'WI', 'WV', 'WY']



#error checking
if state not in states:
	print("Must enter a valid state abbreviation!")
	exit()




with open(file, newline='') as csvfile:
	myfile = csv.reader(csvfile)
	for row in myfile:

		if state in row[6] and (re.match(name,row[0],flags=re.IGNORECASE) or re.match(name,row[1],flags=re.IGNORECASE)):
			print(', '.join(row))