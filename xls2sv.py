# Author: Larry Chu
# $Revision: 1.10 $

# This module generate SystemVerilog source files according to test cases
# defined in an xls file (crater_cb_ana_reg_check_list_*.xls). Registers
# information is digged from file reg_db.py.
# It generate two sv files:
# "checkpoint_both.sv" contains major code; it verifies chekpoints default
# values and checkpoints correlation to registers. "checkpoint_force.sv"
# contains definition of global vars. These two files will be run in the
# simulation environment.

import ComExcel
import os
import re
import time
import sys
import copy
import reg_db

head = '%t CP_SHMOO ERROR'

def findLatestVersion(fnameStart='crater_cb_ana_reg_check_list_'):
	''' Get the name of the latest file within a series of versions
	whose name all start with argument fnameStart. '''
	files = []
	for filename in os.listdir(os.getcwd()):
		if filename.startswith(fnameStart):
			files.append(filename)
	if len(files):
		return os.path.join(os.getcwd(), max(files))
	else:
		raise Exception, 'File that starts with %s not found'%fnameStart

def genCasesTo(cpFile='cp.py'):
	'''
	Extract valid checkpoint test cases from the xls file.
	Put them as a list in file "cp.py".
	'''
	xlsf = ComExcel.ExcelComObj(sheetnum='sheet1', filename=findLatestVersion() )
	rowStart = 1; rowEnd = 200;
	colStart = 1; colEnd = 5;
	colTitle = {1:'checkpoint', 2:'bit_width', 3:'register', 4:'default_value', 5:'direction' }
	listOfCases = []
	row = rowStart
	print 'Start to extract cases from %s'%findLatestVersion()
	for row in range(rowStart, rowEnd+1):
		sys.stdout.write('.')
		aCase = {}
		for col in range(colStart, colEnd+1):
			aCell = xlsf.getCellText(row, col).encode('ascii','ignore')
			if aCell.isdigit(): aCell = int(aCell)
			aCase[colTitle[col]] = aCell
		if type(aCase['bit_width'])==type(1):
			listOfCases.append(aCase)
			#print aCase.values()
		if aCase['checkpoint'] == 'EOF': break
	#xlsf.close()

	cpf=open(cpFile,'w')
	print>>cpf, '# Checkpoint test cases'
	print>>cpf, '# %s, auto-generated from %s'%(time.ctime(), findLatestVersion() )
	print>>cpf, 'listOfCases =',listOfCases
	cpf.close()


def digRegInfoOf(token):
	''' Get the name and width of the corresponding register in the simulation environment. '''
	for reg in reg_db.regDb:
		if token.lower().split('/')[1] == reg['name']:
			name = 'fn%d_'%reg['func'] + reg['name']
			width = 1+reg['bitAddr'][1]-reg['bitAddr'][0]
			break
	else:
		raise Exception, '%s not found in the register file'%token
	return (name, width)

def getRegsOf(case):
	''' Get involved registers' info in the simulation environment of a case '''
	# tokens of involved regs
	tokens = re.findall(r'(RCW/\w+)', str(case['register']), re.IGNORECASE) + \
			 re.findall(r'(fn\d+/\w+)', str(case['register']), re.IGNORECASE)
	listOfRegs = []
	for token in set(tokens): # use set() is to remove duplicates.
		reg = {}
		reg['token'] = token
		bar = digRegInfoOf(token)
		reg['name'] = bar[0]
		reg['width'] = bar[1]
		listOfRegs.append(copy.deepcopy(reg) ) # attention to deepcopy()
	listOfRegs.sort()
	return listOfRegs

#invalidCps = [ #lchu_note: should empty it later
#'rf_aout_en',
#'rf_sampler_test_en',
#'rf_sampler_test_sel',
#]
invalidCps = []
def genCodeIfReg2Cp(case):
	''' correlation: checkpoint is determined by reg '''
	for token in invalidCps:
		if token in case['checkpoint']:
			return '// %s is invalid\n\n'%token
	listOfRegs = getRegsOf(case)
	if not listOfRegs:
		#print 'Case ignored by correlation test:', case
		global numOfIgnoredCases; numOfIgnoredCases += 1

	codeBlock = '`uvm_do_with(this_transfer,{cmd==RST_INIT;})' + ' \n'
	codeBlock += 'begin' + ' \n'
	if listOfRegs:
		codeBlock += r'logic [%d:0] reg_expr;'%(case['bit_width']-1) + ' \n'
		for aReg in listOfRegs:
			codeBlock += r'logic [%d:0] %s;'%(aReg['width']-1, 'var_'+aReg['name']) + ' \n'
	codeBlock += 'activate_func6();' + ' \n'
	cpName = "`ATOP." + '.'.join(case['checkpoint'].split('/') )
	regsNeedUsecal = ['ibt_res', 'ibt_blc']
	for r in regsNeedUsecal:
		if r in cpName: codeBlock += 'clear_usecal();' + ' \n'
	if type(case['default_value']) == int:
		codeBlock += r'if(%s !== %d) $display("%s %s default value err, exp %s0h actual %s0h",$realtime,%s,%s);' %(cpName, case['default_value'], head, case['checkpoint'],'%','%',case['default_value'],cpName) + ' \n'
	if listOfRegs:
		codeBlockRepeat = ''
		for aReg in listOfRegs:
			codeBlock += codeToRandomizeVar(aReg, 'rand')
		for aReg in listOfRegs:
			codeBlockRepeat += r'smb_wr(SMB_ADDR[0], %s, %s);#(tCK*8);'%(aReg['name'], 'var_'+aReg['name']) + ' \n'
		regVarExpr = case['register']
		for aReg in listOfRegs:
			regVarExpr = regVarExpr.replace(aReg['token'], 'var_'+aReg['name'])
		codeBlockRepeat += r'reg_expr=%s;'%regVarExpr + ' \n'
		codeBlockRepeat += r'if(%s !== reg_expr) begin'%(cpName) + ' \n'
		codeBlockRepeat += r'$display("%s %s correlation test fail, exp %s0h actual %s0h",$realtime,reg_expr,%s);'\
					 %(head,case['checkpoint'],'%','%',cpName) + ' \n'
		for aReg in listOfRegs:
			codeBlockRepeat += r'$display("%s DETAIL %s random val is %s0h",$realtime,%s);'\
						 %(head,aReg['token'],'%','var_'+aReg['name']) + ' \n'
		codeBlockRepeat += r'end' + ' \n'
		codeBlock += codeBlockRepeat
		for aReg in listOfRegs:
			codeBlock += codeToRandomizeVar(aReg, 'reverse')
		codeBlock += codeBlockRepeat
	codeBlock += 'end' + ' \n\n'

	return codeBlock

def codeToRandomizeVar(aReg, opt):
	if aReg['name'] == 'fn8_ibt_100ohm':
		code = "var_fn8_ibt_100ohm=$urandom_range('h6f,'h50);" + ' \n'
	#elif aReg['name'] == 'fn8_ibt_150ohm':
		#code = "var_fn8_ibt_150ohm=$urandom_range('h75,'h1c);" + ' \n'
	#elif aReg['name'] == 'fn8_ibt_300ohm':
		#code = "var_fn8_ibt_300ohm=$urandom_range('h3a,'h14);" + ' \n'
	else:
		if opt == 'reverse':
			code = r'%s=~%s;'%('var_'+aReg['name'], 'var_'+aReg['name']) + ' \n'
		elif opt == 'rand':
			code = r'%s=$urandom_range(%d,0);'%('var_'+aReg['name'], 2**aReg['width']-1) + ' \n'
		else:
			raise Exception, 'argument opt must be "rand" or "reverse"'
	return code

def genCodeIfCp2Reg(case):
	''' correlation: reg is determined by checkpoint '''
	listOfRegs = getRegsOf(case)
	if len(listOfRegs) != 1:
		raise Exception, 'one and only one register is allowed here'
	theReg = listOfRegs[0]

	listOfCps = []
	for cpToken in set(case['checkpoint'].split()):
		if cpToken.startswith('xcb_'):
			aCp = {}
			aCp['name'] = '`ATOP.' + cpToken.replace('/', '.')
			aCp['var'] = cpToken.replace('xcb_','var_xcb_').replace('/','_')
			listOfCps.append(copy.deepcopy(aCp))

	defCode = ''
	for aCp in listOfCps:
		defCode += r'logic [%d:0] %s;'%(case['bit_width']-1, aCp['var']) + ' \n'
	codeBlock = '`uvm_do_with(this_transfer,{cmd==RST_INIT;})' + ' \n'
	codeBlock += 'begin' + ' \n'
	codeBlock += r'logic [%d:0] %s;'%(case['bit_width']-1, 'var_'+theReg['name']) + ' \n'
	codeBlock += 'activate_func6();' + ' \n'
	cpNameExpr = case['checkpoint'].replace('xcb_', '`ATOP.xcb_').replace('/','.')
	if type(case['default_value']) == int:
		codeBlock += r'if(%s !== %d) $display("%s %s default value err, exp %s0h actual %s0h",$realtime,%s,%s);' %(cpNameExpr, case['default_value'], head, case['checkpoint'], '%', '%', case['default_value'], cpNameExpr) + ' \n'
	for aCp in listOfCps:
		codeBlock += r'%s=$urandom_range(%d,0);'%(aCp['var'], 2**case['bit_width']-1) + ' \n'
		codeBlock += r'force %s=%s;'%(aCp['name'], aCp['var']) + ' \n'
	codeBlock += r'smb_rd(SMB_ADDR[0], %s, %s);'%(theReg['name'], 'var_'+theReg['name']) + ' \n'
	cpVarExpr =  case['checkpoint'].replace('xcb_','var_xcb_').replace('/','_')
	codeBlock += r'if(%s !== %s) begin'%('var_'+theReg['name'], cpVarExpr) + ' \n'
	codeBlock += r'$display("%s %s correlation test fail, exp %s0h actual %s0h",$realtime,%s,%s);'\
				 %(head, case['register'],'%','%', cpVarExpr, 'var_'+theReg['name']) + ' \n'
	codeBlock += r'end' + ' \n'
	for aCp in listOfCps:
		codeBlock += r'release %s;'%(aCp['name']) + ' \n'
	codeBlock += 'end' + ' \n\n'

	return codeBlock, defCode


numOfIgnoredCases = 0
def genSourceFiles(listOfCases, fileMajor = 'checkpoint_both.sv', fileDef = 'checkpoint_force.sv' ):
	'''
	Generate two SystemVerilog source files to run simulation.
	"checkpoint_both.sv" contains major code, and is included in "checkpoint_shmoo.sv" in sim.
	"checkpoint_force.sv" contains definitions of global vars, and is included in "mb_param.sv" in sim.
	'''
	print '\nStart to generate sv files'
	fdef = open(fileDef, 'w')
	fdef.write('//--- Checkpoint global vars definition -----------------------------\n')
	fdef.write('// Code auto-generated at %s\n\n'%time.ctime() )
	fmajor = open(fileMajor,'w')
	fmajor.write('//--- Checkpoint correlation-to-reg and read-default test -----------------------------\n')
	fmajor.write('// Code auto-generated at %s\n'%time.ctime() )
	fmajor.write('// Total cases: %d\n\n'%len(listOfCases) )

	for caseIndex, aCase in enumerate(listOfCases):
		sys.stdout.write('.')
		if aCase['direction'] == 'input':
			aCodeBlock = genCodeIfReg2Cp(aCase)
		elif aCase['direction'] == 'output':
			aCodeBlock, defCode = genCodeIfCp2Reg(aCase)
			fdef.write(defCode)
		else:
			print aCase
			raise Exception, 'direction must be "input" or "output" '
		fmajor.write('// --- case %d --------------------------------------------\n'%(caseIndex) )
		fmajor.write(aCodeBlock)

	fdef.close()
	fmajor.write('\n// %d cases ignored by correlation test\n'%(numOfIgnoredCases) )
	fmajor.close()


def run():
	genCasesTo('cp.py')
	import cp; genSourceFiles(cp.listOfCases)
	os.system('gvim Checkpoint_both.sv')

if __name__ == '__main__':
	try:
		run()
	except:
		import traceback; traceback.print_exc();
	finally:
		raw_input("\n---Press ENTER to quit---")

