#!/usr/bin/env python3
"""
QLever W3C-tests Parser Tool
"""

# /mnt/c/Users/Joao/Desktop/Mestrado/ERASMUS/Winter Semester/git_ad_freiburg_qlever/qlever-code/
# /mnt/c/Users/Joao/Desktop/Mestrado/ERASMUS/Winter Semester/git_joaomarques_qlever/qlever/

import glob
import json
import os
import platform
import re
import signal
import socket
import subprocess
import sys
import time
import urllib
import urllib.parse
import urllib.request
import io

from pathlib import Path
from typing import TextIO, Dict, Any
import jsoncomparison  # python3.XX -m pip install -U pip jsoncomparison
import requests
import yaml

from bs4 import BeautifulSoup  # apt-get install python3-bs4
from requests.adapters import HTTPAdapter, Retry


# return True if line is fully commented or empty
def ignore_line(linha: str) -> bool:
    if '#### Request' in linha:  # Protocol tests
        return False
    if '#### Response' in linha:  # Protocol tests
        return False
    res = re.search('^[ \t.]*\\n', linha)  # empty lines
    if res:
        return True
    if '#' in linha:
        res = re.search('^[ ]*#', linha)  # commented lines
        if res:  # comments in valid lines will be stripped out forward
            return True
    return False


# convert srx-file, together with sparql-input (query), to Qlever-YAML
def srx_to_yaml(file_in: str, group_name: str, query_file_name: str, query_type: str, query_raw: str, file_out: str):
    with open(Path(file_in)) as fp:
        soup = BeautifulSoup(fp, 'lxml')

        # ** variables **
        variables = []
        variables_qlever = []
        for variables_tag in soup.findAll('variable'):
            variables.append(variables_tag['name'])
            variables_qlever.append('?' + variables_tag['name'])

        # ** binding **
        number_columns = len(variables)
        results = soup.findAll('result')
        number_rows = len(results)
        checks = [dict([('num_cols', number_columns)]),
                  dict([('num_rows', number_rows)]),
                  dict([('selected', variables_qlever)])]

        # ** order_by **
        order_by_index = query_raw.rfind("ORDER BY")
        exists_index = order_by_index
        order_by_dir = None
        if order_by_index:
            order_by_index += len("ORDER BY") + len(" ")
            order_by_content = query_raw[order_by_index:]

        if order_by_index and order_by_content.startswith("ASC"):
            order_by_dir = "ASC"
            order_by_index + len("ASC") + len(" (")
        elif order_by_index and order_by_content.startswith("DESC"):
            order_by_dir = "DESC"
            order_by_index + len("DESC") + len(" (")
        elif exists_index != -1:
            print("Order By Parser Error: " + order_by_content)
            exit(1)

        if order_by_dir:
            order_by_index_end = order_by_content.rfind(")")
            order_by_value = order_by_content[order_by_index:order_by_index_end - 1]

        # ** row_data_types **
        variables_data_map = dict()
        for var in variables:
            variables_data_map.update({var: []})

        row_list = []
        for result_tag in results:
            row = []
            variables_found = []
            for tag in result_tag:
                if not tag == '\n':
                    datatype = None
                    var = tag['name']
                    # add variables to check if column missing at the end
                    if var not in variables_found:
                        variables_found.append(var)
                    next_elem = tag.next_element
                    if next_elem.name == 'literal':
                        datatype_exist = next_elem.attrs
                        if datatype_exist:
                            datatype_value = datatype_exist['datatype']  # RAW datatype value
                            datatype = datatype_value[datatype_value.rfind('#') + 1:]  # parsed datatype value
                    value = next_elem.contents[0]  # variable value
                    if datatype:
                        column_content = dict([('type', next_elem.name), ('value', str(value)), ('datatype', datatype)])
                        datatype_var = variables_data_map[var]
                        # multiple datatypes
                        if datatype not in datatype_var:
                            datatype_var.append(datatype)
                            variables_data_map[var] = datatype_var
                    else:
                        if next_elem.name in ['iri', 'uri', 'url', 'urn']:
                            # ADD '<' and '>' CHARACTERS
                            column_content = dict([('type', next_elem.name), ('value', '<' + str(value) + '>')])
                        else:
                            column_content = dict([('type', next_elem.name), ('value', str(value))])
                        datatype_var = variables_data_map[var]
                        # multiple datatypes
                        if 'string' not in datatype_var:
                            datatype_var.append('string')
                            variables_data_map[var] = datatype_var
                    # column_var = dict([("?" + var, column_content)])  # ADD '?' CHARACTER
                    column_var = dict([(var, column_content)])
                    row.append(column_var)

            # if a column missing then sets its value to null
            if not len(variables_found) == len(variables):
                for _var in variables:
                    if _var not in variables_found:
                        # _column_var = dict([("?" + _var, None)])  # ADD '?' CHARACTER
                        _column_var = dict([(_var, None)])
                        row.append(_column_var)

            # checks.append(dict([('contains-row', row)]))
            row_list.append(dict([('contains-row', row)]))

        # ** Check different datatypes for each variable **
        # if not type == literal then string
        # elif datatype not in literal then string
        # else datatype
        # if multiple then concat(datatype_1, '|', datatype_n)
        #       ==> row_datatype 'string' (if exists) must be at the end of it
        # checks.append(dict([('row_data_types', row_data_types)]))

        for var in variables_data_map:
            # row_datatype 'string' (if exists) must be at the end of it [generic type]
            if 'string' in variables_data_map[var]:
                res = variables_data_map[var]
                res.remove('string')
                res.append('string')  # move 'string' to the end of the list
                variables_data_map[var] = res

        final_row_data_types = []
        for var in variables:
            data_var = variables_data_map[var]
            if len(data_var) == 1:
                final_row_data_types.append(data_var[0])
            else:
                temp_res = ""
                for index, data in enumerate(data_var):
                    if index == 0:
                        temp_res += data
                    else:  # index != 0:
                        temp_res += "|" + data
                final_row_data_types.append(temp_res)

        # ** Append, at this point, 'row_data_types' to 'checks' (ordered yaml) **
        checks.append(dict([('row_data_types', final_row_data_types)]))

        # ** Append, at this point, 'row_list' to 'checks' (ordered yaml) **
        for elem in row_list:
            checks.append(elem)

        # ** Append, at this point, 'order_by_dir' to 'checks' (ordered yaml) **
        if order_by_dir:
            checks.append(dict([('order_string', dict([('dir', order_by_dir), ('var', order_by_value)]))]))

        # ** Create, at this point, 'queries_header' **
        queries_header = [dict([('query', query_file_name), ('type', query_type),
                                ('sparql', query_raw), ('checks', checks)])]

        # ** Create, at this point, 'yaml_file' with the header and its contents **
        yaml_file = dict([('name', group_name), ('queries', queries_header)])

        # ** Export yaml file to correct path **
        with open(Path(file_out), 'w') as output:
            output.write('---\n')
            output.write(yaml.dump(yaml_file, sort_keys=False))


# header ==> retrieve (label, comment, [tests_names])
def parse_manifest_header(_header: [str]) -> (str, str, [str]):
    _tests_names = []
    _label = None
    _comment = None
    for entry in _header:
        if 'rdfs:label' in entry:
            _label = entry[entry.find("\"") + 1: entry.rfind("\"")]
        elif re.search('^[ \t]*(\()?[ \t]*:', entry):  # Test Name
            words = entry.split()
            for word in words:
                if word[0] == '(':
                    word = word[1:]
                if len(word) > 1:
                    if word[0] == ':':
                        if word[-1] == '.':
                            word = word[:-1]
                        if word[-1] == ')':
                            word = word[:-1]
                        _tests_names.append(word[1:])
            '''
            name = entry[entry.find(":") + 1: entry.find("\n")]
            if name[-1] == ' ':
                name = name[:-1]
            _tests_names.append(name)
            '''
        elif '    rdfs:comment' in entry:
            _comment = entry[entry.find("\"") + 1: entry.rfind("\"")]
    return _label, _comment, _tests_names


# tests_map ==> retrieve (name, type, mf_name, approval_value, approval_by, action[acts], result[res])
def parse_manifest_tests(_tests_map: dict, test_names: [str]):
    _manifest_tests_parsed = []
    for index in _tests_map:

        _name = _type = _mf_name = _approval_value = _approval_by = None
        _mf_description = _seeAlso = _mf_resultCardinality = None
        _action = []
        _result = []
        _comment = dict()
        _query_form = dict()
        _request = _response = False
        _requires = []
        _notable = []
        _graphData = []
        _serviceData = []
        _entailmentProfile = []
        _entailmentRegime = []
        _feature = dict()

        _request_content = []
        _response_content = []

        test = _tests_map[index]
        action_start = result_start = comment_start = start_type = graphData_start = serviceData_start = False
        level = 0
        for entry in test:
            if ignore_line(entry):  # if the line is entirely a comment
                continue
            if entry[0] == ':':
                _response = False
            if '#### Response' in entry:
                _request = False
                _response = True
                # print("< response_line >")
            if '#### Request' in entry:
                _request = True
                _response = False
                # print("< request_line >")
            if _request:
                # print("_parse_request")
                _request_content.append(entry)
            elif _response:
                # print("_parse_response")
                _response_content.append(entry)
            else:
                # SEPARATE LINE BY WORDS
                words = entry.split()

                # CONCAT WORDS WITH SPACE IF "\"" IS PRESENT
                temp = []
                temp_start = False
                temp_words = []
                for word in words:
                    if word[0] == '"' and word[-1] == ';':
                        word = word[:-1]
                    if word[0] == word[-1] == '"':
                        temp_words.append(word)
                    elif temp_start or ("\"" in word):
                        if "\"" in word:
                            temp_start = not temp_start
                        temp.append(word)
                        if not temp_start:
                            temp_words.append(" ".join(temp))
                            temp = []
                    else:
                        temp_words.append(word)
                words = temp_words
                del temp_start, temp_words, temp, word

                # REMOVE WORDS AFTER COMMENT CHARACTER IN ONE WORD
                removal = []
                remove_start = False
                for word in words:
                    if word.startswith("#"):
                        removal.append(word)
                        remove_start = True
                    elif remove_start:
                        removal.append(word)
                for remove_word in removal:
                    words.remove(remove_word)
                del remove_start, removal
                # print(words)

                # DEBUG
                if len(words) == 0:
                    print("[parse_manifest_tests] [entry: %s] Something went wrong: "
                          "'words' should be > 0" % entry)
                    continue

                # Parse line (entry/words)
                first_word = words[0]
                if first_word[0] == ':':
                    _name = first_word[1:]  # ignore ':' character
                    if len(words) >= 3:
                        second_word = words[1]
                        third_word = words[2]
                        _type = dict([(second_word, third_word)])
                    else:
                        start_type = True
                elif 'name' in first_word:
                    second_word = words[1]
                    _mf_name = dict([(first_word, second_word)])
                elif 'mf:description' in first_word:
                    second_word = words[1]
                    _mf_description = dict([(first_word, second_word)])
                elif 'approval' in first_word:
                    second_word = words[1]
                    _approval_value = dict([(first_word, second_word)])
                elif 'approvedBy' in first_word:
                    second_word = words[1]
                    _approval_by = dict([(first_word, second_word)])
                elif ':seeAlso' in first_word:
                    second_word = words[1]
                    _seeAlso = dict([(first_word, second_word)])
                elif 'action' in first_word:
                    line_length = len(words)

                    # check what type of result [query, update,
                    if '[' not in words and line_length > 1:  # result in the same line
                        second_word = words[1]
                        _action.append([first_word, second_word])
                    else:  # count '[' in this line
                        action_start = True
                        if line_length == 1:
                            continue

                    level += entry.count('[')
                    level -= entry.count(']')

                    if level == 0:
                        if line_length >= 6:
                            action_start = False
                            word_start = 2  # index starting at '0'
                            while word_start < line_length - 1:
                                _key_result = words[word_start]
                                _value_result = words[word_start + 1]
                                _action.append([_key_result, _value_result])
                                word_start += 3
                            del _key_result, _value_result

                        elif line_length >= 4:
                            action_start = False
                            third_word = words[2]
                            fourth_word = words[3]
                            _key_result = third_word
                            _value_result = fourth_word
                            _action.append([_key_result, _value_result])
                            del _key_result, _value_result

                        elif line_length == 1:
                            action_start = True
                            continue

                        elif line_length == 3:
                            action_start = False
                            second_word = words[1]
                            third_word = words[2]
                            if third_word == ';' or third_word == '.' or third_word == ';.':  # '[' not present
                                continue
                            _key_result = second_word
                            _value_result = third_word
                            _action.append([_key_result, _value_result])
                            del _key_result, _value_result
                            continue
                        else:
                            1 == 1
                            print("else {  elif line_length < 4 and != 1}")
                            print("else: line_length = " + str(line_length))
                            print("else: words = " + str(words))

                    else:
                        # level > 0
                        if line_length == 5:
                            third_word = words[2]
                            fourth_word = words[3]
                            _key_result = third_word
                            _value_result = fourth_word
                            _action.append([_key_result, _value_result])
                            del _key_result, _value_result
                        elif line_length == 2 and words[1] == '[':
                            action_start = True
                            continue
                        else:
                            1 == 1
                            print("first_word = action: level > 0 AND line_length != 5 AND != 2")
                            print("words = " + str(words))
                elif first_word == 'mf:result':
                    line_length = len(words)
                    if line_length == 1:
                        result_start = True
                        continue
                    # check what type of result [query, update, *****************************************
                    if '[' not in words:  # result in the same line
                        second_word = words[1]
                        if second_word[-1] == ';':
                            second_word = second_word[:-1]
                        if second_word[-1] == '.':
                            second_word = second_word[:-1]
                        _result.append(second_word)
                    else:  # '[' in this line
                        result_start = True
                        level += 1

                        # check if ']' (close) in this line as well
                        if ']' in words:
                            level -= entry.count(']')
                            if level == 0:
                                result_start = False

                        #  Check if one result in this line (AND possible in following lines)
                        if line_length >= 4 and words[2] != "ut:graphData":
                            third_word = words[2]
                            fourth_word = words[3]
                            _key_result = third_word
                            _value_result = fourth_word
                            _result.append([_key_result, _value_result])
                            del _key_result, _value_result
                        elif line_length >= 4 and words[2] == "ut:graphData":
                            graphData_start = True
                            second_word = words[1]  # == '['
                            third_word = words[2]  # == 'ut:graphData'
                            fourth_word = words[3]  # == '['
                            fifth_word = words[4]
                            sixth_word = words[5]
                            _graphData.append([fifth_word, sixth_word])
                            if ']' in words:
                                graphData_start = False
                                _action.append('graphData')
                                _action.append(_graphData)  # list
                                _graphData = []
                            # do stuff
                        elif line_length == 2 and words[1] == '[':
                            result_start = True
                            continue
                        else:
                            1 == 1
                            print(
                                "else {line_length >= 4 and words[2] != 'ut:graphData'} elif {line_length >= 4 and words[2] == 'ut:graphData'}")
                            print("else: {line_length = " + str(line_length) + "} {words = " + str(words) + "}")
                    if action_start:
                        1 == 1
                        print("[parse_manifest_tests] [query: %s] Something went wrong: "
                              "'action_start' should be false when parsing 'result' tag" % _name)

                # Entailment Evaluation tests are special query evaluation tests that additionally (slightly ab-)use
                # the sd:entailmentRegime and, optionally, the sd:EntailmentProfile properties from the SPARQL 1.1
                # Service Description vocabulary to further specify the object of the mf:action property, indicating
                # the expected entailment regime for graphs in the dataset and, where applicable, which OWL profile that
                # test satisfies.

                # https://www.w3.org/TR/owl2-primer/#OWL_2_Profiles

                elif 'ntailmentProfile' in first_word:
                    for i, word in enumerate(words):
                        if i > 0:
                            if ')' in word:
                                if word != ')':
                                    _entailmentProfile.append(word[:-1])
                                _action.append([first_word, _entailmentProfile])
                            elif ']' in word:
                                if word != ']':
                                    _entailmentProfile.append(word[:-1])
                                if action_start:
                                    level -= 1
                                    action_start = False
                            elif '(' in word and word != '(':
                                _entailmentProfile.append(word[1:])
                            elif word != '(' and word != ')' and word != ';':
                                _entailmentProfile.append(word)

                # A SPARQL implementation passes a query evaluation test if its answers over any graphs in the dataset
                # using the sd:entailmentRegime property comply with the criteria formalised in the SPARQL 1.1
                # Entailment Regimes document. Apart from that, passing tests is as defined for query evaluation tests.

                # https://www.w3.org/TR/sparql11-entailment/

                elif 'ntailmentRegime' in first_word:
                    for i, word in enumerate(words):
                        if i > 0:
                            if ')' in word:
                                if word != ')':
                                    _entailmentRegime.append(word[:-1])
                                _action.append([first_word, _entailmentRegime])
                            elif ']' in word:
                                if word != ']':
                                    _entailmentRegime.append(word[:-1])
                                if action_start:
                                    level -= 1
                                    action_start = False
                            elif '(' in word and word != '(':
                                _entailmentRegime.append(word[1:])
                            elif word != '(' and word != ')' and word != ';':
                                _entailmentRegime.append(word)
                elif ':requires' in first_word:
                    second_word = words[1]
                    _requires.append(second_word)
                elif ':notable' in first_word:
                    second_word = words[1]
                    _notable.append(second_word)
                elif 'mf:resultCardinality' == first_word:
                    second_word = words[1]
                    _mf_resultCardinality = second_word
                elif 'mf:feature' == first_word:
                    second_word = words[1]
                    _feature = dict([(first_word, second_word)])
                elif 'rdf:type' == first_word:
                    # Check if need to open levels AND if open-close AND if simple {tag key value}
                    # ADD WORDS BETWEEN PARENTHESIS
                    second_word = words[1]
                    _type = dict([(first_word, second_word)])
                elif 'queryForm' in first_word:
                    second_word = words[1]
                    _query_form_key = first_word
                    _query_form_value = second_word
                    _query_form.update({_query_form_key: _query_form_value})
                    del _query_form_key, _query_form_value
                elif '[' in first_word and len(words) == 1:
                    level += 1
                elif 'comment' in first_word:
                    _key_comment = first_word
                    if len(words) >= 2:  # value in this line
                        second_word = words[1]
                        _value_comment = second_word
                        _comment.update({_key_comment: _value_comment})
                        del _key_comment, _value_comment
                    else:  # value in next line
                        _key_comment = first_word
                        comment_start = True
                else:  # subLevels
                    if action_start:
                        level += entry.count('[')
                        level -= entry.count(']')

                        if 'ut:graphData' in first_word and '[' in words:
                            graphData_start = True
                            second_word = words[1]  # second_word == '['
                            third_word = words[2]
                            fourth_word = words[3]
                            _graphData.append([third_word, fourth_word])
                            if ']' in words:
                                graphData_start = False
                                _action.append(['graphData', _graphData])
                                _graphData = []
                            continue

                        if ':serviceData' in first_word and '[' in words:
                            serviceData_start = True
                            if len(words) > 2:
                                second_word = words[1]  # second_word == '['
                                third_word = words[2]
                                fourth_word = words[3]
                                _serviceData.append([third_word, fourth_word])
                                if ']' in words:
                                    serviceData_start = False
                                    _action.append(['serviceData', _serviceData])
                                    _serviceData = []
                            continue

                        if graphData_start:
                            if first_word != ']':
                                second_word = words[1]
                                _graphData.append([first_word, second_word])
                            if ']' in words:
                                graphData_start = False
                                _action.append(['graphData', _graphData])
                                _graphData = []
                            continue

                        if serviceData_start:
                            if first_word != ']':
                                second_word = words[1]
                                _serviceData.append([first_word, second_word])
                            if ']' in words:
                                serviceData_start = False
                                _action.append(['serviceData', _serviceData])
                                _serviceData = []
                            continue

                        if first_word == '[':
                            second_word = words[1]
                            third_word = words[2]
                            _key_action = second_word
                            _value_action = third_word
                        else:
                            if first_word == ']':
                                action_start = False
                                continue
                            _key_action = first_word
                            second_word = words[1]
                            _value_action = second_word
                        if _value_action[-1] == ';' or _value_action[-1] == '.':
                            _value_action = _value_action[:-1]
                        _action.append([_key_action, _value_action])
                        del _key_action, _value_action

                        if level == 0:
                            action_start = False
                    elif result_start:

                        if first_word == ']':
                            level -= 1
                            result_start = False
                            continue

                        if 'ut:graphData' in words and '[' in words:
                            graphData_start = True
                            second_word = words[1]  # second_word == '['
                            third_word = words[2]
                            fourth_word = words[3]
                            _graphData.append([third_word, fourth_word])
                            if ']' in words:
                                graphData_start = False
                                _result.append(['graphData', _graphData])  # list
                                _graphData = []
                            continue

                        if graphData_start:
                            second_word = words[1]
                            _graphData.append([first_word, second_word])
                            if ']' in words:
                                graphData_start = False
                                _result.append(['graphData', _graphData])
                                _graphData = []
                            continue

                        if entry.find(":") != -1:  # if not a new test-entry (unlikely)
                            _key_result = entry[entry.find(":") + len(':'): entry.find(" <")]
                            _value_result = entry[entry.find("<") + 1: entry.find(">")]
                            _result.append([_key_result, _value_result])
                            del _key_result, _value_result
                        if ']' in words:
                            level -= 1
                        if level == 0:
                            result_start = False
                    elif comment_start:
                        _value_comment = _key_comment = first_word
                        _comment.update({_key_comment: _value_comment})
                        del _key_comment, _value_comment
                        comment_start = False
                    elif start_type:
                        second_word = words[1]
                        _type = dict([(first_word, second_word)])
                        start_type = False

                    elif first_word in test_names:  # abnormal initiation of test (solution)
                        _name = first_word
                        if len(words) >= 3:
                            second_word = words[1]
                            third_word = words[2]
                            _type = dict([(second_word, third_word)])
                        else:
                            start_type = True
                    elif 'body encoded in utf-16' in entry:
                        continue  # ignore because it is also declared in the body (charset)
                    else:
                        1 == 1
                        print("[parse_manifest_tests] [query: %s] Something went wrong: "
                              "unexpected behaviour (else-catch)" % entry)
        if level != 0:
            print("[parse_manifest_tests] [query: %s] Something went wrong: level [%d] should not be != 0 "
                  % (_name, level))
        else:
            q_resultado = dict([('name', _name), ('type', _type), ('mf_name', _mf_name), ('seeAlso', _seeAlso),
                                ('mf_description', _mf_description), ('mf:resultCardinality', _mf_resultCardinality),
                                ('approval_value', _approval_value), ('_approval_by', _approval_by),
                                ('actions', _action), ('result', _result), ('comment', _comment),
                                ('query_form', _query_form), ('requires', _requires), ('notable', _notable),
                                ('feature', _feature), ('request', _request_content), ('response', _response_content)])
            _manifest_tests_parsed.append(q_resultado)

    return _manifest_tests_parsed


def get_test_names(header: [str]) -> [str]:
    names = []
    start_names = False
    for line in header:
        if 'mf:entries' in line or start_names:
            start_names = True  # mainly for 'mf:entries'
            words = line.split()
            res = re.search('^[ \t]*\n', line)
            for word in words:
                if word != '(' and word.startswith('('):
                    names.append(word[1:])
                elif word != ')' and word.endswith(')'):
                    names.append(word[:-1])
                elif word != ').' and word.endswith(').'):
                    names.append(word[:-2])
                elif word != 'mf:entries' and word != '(' and word != ')' and word != '.' and not res:
                    names.append(word)
    return names


def parse_manifest(manifest_file_path: str, manifest_file_fp: TextIO) -> [dict]:
    lines = manifest_file_fp.readlines()

    '''
    ALL POSSIBLE PREFIXES: 
    
    dawgt: RDF Data Access Working Group Test
    ut: Update Test
    qt: Query Test
    mf: Manifest Test
    rdfs: Resource Description Framework Schema
    rdf: Resource Description Framework
    sd: Service Description
    ent: Entailment
    rs: Result-Set
    : Manifest
    
    '''

    prefixes = []
    header = []
    start_header = stop_header = False
    expected_tests = 0

    tests_header_names = []
    tests_number = 0
    tests_map = dict()
    test_temp_str = []

    # divide structure of Manifest [prefix, header { label, comment, [tests_names] }, [tests]]
    for line in lines:
        res = re.search('^[ \t]*:', line)  # catch the initiation/name of a test ( ':' )
        if line[0] == '@':  # prefix
            prefixes.append(line)
        # elif line[0] == ':' and stop_header:  # new test
        elif res and stop_header:  # new test (split by tests)
            if start_header:
                start_header = False  # (redundant)
            if tests_number > 0:  # append last parsed test to map
                tests_map.update({tests_number: test_temp_str})
                test_temp_str = []  # reset the list for the next structured test
            tests_number += 1
            test_temp_str.append(line)
            temp_test_name = line.split()[0]
            tests_header_names.append(temp_test_name)
        elif line.startswith("[]") or line.startswith("<>") or start_header:  # header
            start_header = True
            if line == "\n":
                continue  # ignore empty-newLine [start_header]
            header.append(line)
            res = re.search('^[ \t]*(\()?[ \t]*:', line)  # catch the initiation/name of a test in header ( ':' )
            if res:
                expected_tests += 1  # value better parsed in parse_manifest_header
            if ')' in line:  # End of Header
                stop_header = True
                start_header = False
                if expected_tests == 0:  # if abnormal name-test initiation
                    for name in get_test_names(header):
                        tests_header_names.append(name)
        else:  # rest (tests)
            if line == "\n":
                continue  # ignore empty-newLine
            if expected_tests == 0:  # alternative for abnormal structure (without ':')
                first_word = line.split()[0]
                if first_word in tests_header_names:
                    if tests_number > 0:  # append last parsed test to map
                        tests_map.update({tests_number: test_temp_str})
                        test_temp_str = []  # reset the list for the next structured test
                    tests_number += 1
                test_temp_str.append(line)
            else:
                test_temp_str.append(line)
    tests_map.update({tests_number: test_temp_str})  # append the last test to map

    del test_temp_str, lines, start_header, line

    # prefixes
    # header ==> retrieve (label, comment, [entries_names]
    label, comment, tests_names = parse_manifest_header(header)
    del header

    expected_tests = len(tests_names)
    if tests_number != expected_tests:
        print("[parse_manifest] WARNING: tests_number[%d] != expected_tests [%d] :: " % (tests_number, expected_tests))
    else:
        print("[parse_manifest] INFO: tests_number[%d] == expected_tests [%d] :: " % (tests_number, expected_tests))

    if expected_tests != len(tests_header_names):
        print("[parse_manifest] WARNING: expected_tests[%d] != tests__names [%d] :: "
              % (expected_tests, len(tests_header_names)))
        if expected_tests == 0:
            tests_names = tests_header_names
            print("\tAbnormal tests naming found. Refactoring tests_names to tests_header_names")
            print("\ttests_header_names = " + str(tests_header_names))
    else:
        print("[parse_manifest] INFO: expected_tests[%d] == tests__names [%d] :: "
              % (expected_tests, len(tests_header_names)))

    del expected_tests

    # tests_map ==> retrieve (name, type, mf_name, approval_value, approval_by, action[acts], result[res])
    tests = parse_manifest_tests(tests_map, tests_header_names)
    del tests_map

    # get parent-dir (absolute) path from manifest_file
    _parent_dir = str(Path(manifest_file_path).parent.absolute())

    # tests to be removed (declared but not invoked)
    remove_tests = []

    if len(tests) < tests_number:
        print("[parse_manifest] ERROR: #tests after parsing_tests == " + str(len(tests)))
    del tests_number

    for index, test in enumerate(tests):
        result_suffix = _request_file = _query_file_name = _in_file = _in_file_name = yamls_dir = _out_file = None

        # add label to individual test-dictionary
        test.update({'label': label})
        # add manifest-file to individual test-dictionary
        test.update({'manifest': manifest_file_path})
        # add directory to individual test-dictionary
        test.update({'dir': _parent_dir})
        # add sparql-version-test to individual test-dictionary
        if 'data-r2' in manifest_file_path:
            test.update({'version': 'Sparql 1.0'})
        elif 'data-sparql11' in manifest_file_path:
            test.update({'version': 'Sparql 1.1'})

        test_name = test['name']
        if test_name is None:
            print("\n\t\tERROR: name is not present in test:= " + str(test))
        else:
            print("\n\t\tname = " + test_name)

        if test_name in tests_names:

            # Check what results (files) are expected to match (if empty, check if the test-query is accepted)

            resultZero = False
            option = 0
            entailmentRegime = entailmentProfile = False
            graphDataResult = graphDataAction = False
            requires = False
            notable = False
            feature = False

            if 'result' not in test or test['result'] is None or test['result'] == ['[]'] or test['result'] == []:
                resultZero = True

            if resultZero:
                print("\t\t »» Empty result-test ««")

            print("\t\ttype = " + str(test['type']))

            if 'type' in test:
                type_value = list(test['type'].values())[0]  # only one value-type anyway
                if 'PositiveSyntax' in type_value:
                    option = 1
                elif 'NegativeSyntax' in type_value:
                    option = 2
                elif 'QueryEvaluation' in type_value:
                    option = 3
                    # Cardinality
                    if test['mf:resultCardinality'] is not None:
                        option = 31  # sublevel 3.1
                    # Entailment
                    actions_lst = test['actions']
                    print("action_lst = " + str(actions_lst))
                    for action_item in actions_lst:
                        for action_subitem in action_item:
                            if 'ntailmentRegime' in action_subitem:
                                entailmentRegime = True
                            elif 'ntailmentProfile' in action_subitem:
                                entailmentProfile = True
                    if entailmentRegime and entailmentProfile:
                        option = 321  # sublevel 3.2.1
                    elif entailmentRegime:
                        option = 322  # sublevel 3.2.2
                    elif entailmentProfile:
                        option = 323  # sublevel 3.2.3
                elif 'UpdateEvaluation' in type_value:
                    option = 4
                elif 'CSVResultFormat' in type_value:
                    option = 5
                elif 'GraphStoreProtocol' in type_value:
                    option = 6
                elif 'ProtocolTest' in type_value:
                    option = 7
                elif 'ServiceDescription' in type_value:
                    option = 8
                elif 'NegativeUpdateSyntax' in type_value:
                    option = 9
                elif 'PositiveUpdateSyntax' in type_value:
                    option = 10
                else:
                    print('type_value = ' + str(type_value))
                    option = 99  # Unexpected type value
            else:
                print('type not in test')  # option = 0

            if test['requires']:
                requires = True  # implications ???

            if test['notable']:
                notable = True  # implications ???

            if test['feature']:
                feature = True  # implications ???

            if test['actions'] == ['[]'] or test['actions'] == []:
                option = 11  # HTTP  --------------------------------------
                print("\t\t\tassigned_type_number = " + str(option))
                print("\t\ttest = " + str(test))
                print("\t\t\trequest = " + str(test['request']))
                print("\t\t\tresponse = " + str(test['response']))
            else:
                print("\t\t\tassigned_type_number = " + str(option))
                print("\t\ttest = " + str(test))
                print("\t\tactions = " + str(test['actions']))

            print("\t\tresult = " + str(test['result']))

            for result_name in test['result']:
                print("\t\t\t »» Checking result contents.... ««")

                # create Yaml if necessary (and folder named 'yamls')
                # if result_name is NOT a list, then ONLY ONE iteration (break)

                # ACCEPT ANY ORDER (query->data or data->query)

                for num, result_name_sublevel in enumerate(result_name):
                    print("\t\t\t\t »»» Num = " + str(num))
                    if isinstance(result_name, list) and all(isinstance(elem, str) for elem in result_name):
                        if '<' == result_name_sublevel[0]:
                            result_name_sublevel = result_name_sublevel[1:]
                        if '>' == result_name_sublevel[-1]:
                            result_name_sublevel = result_name_sublevel[:-1]
                        result_suffix = result_name_sublevel
                        if 'data' in result_suffix:
                            continue
                        if 'result' in result_suffix:
                            continue
                        if 'success' in result_suffix:
                            continue
                        result_suffix = result_suffix[result_suffix.rfind('.'):]
                    elif isinstance(result_name, list) and any(isinstance(elem, list) for elem in result_name):
                        print("\t\t\t\t\t >> graphData may be present in result")
                        graphDataResult = True
                        break  # *************************************************************************************
                    else:  # Only one element
                        if '<' == result_name[0]:
                            result_name = result_name[1:]
                        if '>' == result_name[-1]:
                            result_name = result_name[:-1]
                        result_suffix = result_name
                        result_suffix = result_suffix[result_suffix.rfind('.'):]

                    if result_suffix == '.srx' or result_suffix == '.ttl':
                        print("\t\t\t\t\tparse_to_yaml { .ttl or .srx }")

                        # Check what actions are needed
                        if 'actions' in test:
                            actions_length = len(test['actions'])
                            # print("actions_length = " + str(actions_length))
                            key = key_val = None
                            value = value_val = None
                            flag = 0

                            for key_value in test['actions']:
                                # print("key_value = " + str(key_value))
                                if flag == 1:
                                    value = key_value[0]
                                    value_val = key_value[1]
                                    if ':data' in value:
                                        flag += 1
                                    else:
                                        continue
                                if flag == 0:
                                    key = key_value[0]
                                    key_val = key_value[1]
                                    if ':query' in key:
                                        flag += 1
                                    continue
                                if flag == 2:
                                    # (key_val, value_val)

                                    '''
                                    _query_file_name = test['actions']['query']
                                    _request_file = _parent_dir + '/' + _query_file_name
                                    _in_file_name = test['actions']['data']
                                    _in_file = _parent_dir + '/' + _in_file_name
                
                                    yamls_dir = _parent_dir + '/yamls'
                                    _out_file = yamls_dir + '/' + label + "_" + test['name'] + '.yaml'
                                    with open(_request_file, 'r') as rq_file:
                                        _query_sparql = rq_file.read()
                                    # Create YAML in the 'yamls' folder
                                    os.makedirs(os.path.dirname(_out_file), exist_ok=True)  # if dir exists, leaves it unaltered
                                    if result_suffix == '.srx':
                                        srx_to_yaml(_in_file, label, _query_file_name, 'no-text', _query_sparql, _out_file)
                                    else:
                                        ttl_to_yaml()
                
                                    # add yaml (file-name) to individual test-dictionary
                                    test.update({'yaml': _out_file})
                
                                    # update actions/results with absolute-paths
                                    # test.update({'actions': final_actions})
                                    # test.update({'results': final_results})
                                    '''

                                    flag = 0
                                    print("\t\t\t\t\tparse_to_yaml { action_flag == 0 }")
                    elif result_name == '[]':
                        continue
                    elif result_suffix == '.rdf':
                        print("\t\t\t\t\tparse_rdf")
                    elif result_suffix == '.srj':
                        print("\t\t\t\t\tparse_srj")
                    elif result_suffix == '.tsv':
                        print("\t\t\t\t\tparse_tsv")
                    elif result_suffix == '.csv':
                        print("\t\t\t\t\tparse_csv")
                    else:  # test[result] != dic NOR result.suffix == '.srx | .ttl'
                        1 == 1
                        print("ELSE: " + result_suffix + "\n")

                    if not isinstance(result_name, list):
                        break  # forgot why

            # update tests_map

            # ******** option
            # ******** graphDataResult/graphDataAction
            # ******** requires  »»» XsDateOperations/StringSimpleLiteralCmp/KnowTypesDefault2Neq/LangTagAwareness/notable/IllFormedLiteral

            tests[index] = test

        else:
            # test declared in manifest but not invoked
            # ** unnecessary **
            remove_tests.append(test)
            print("[parse_manifest] TESTS-index = " + str(index))
            print("[parse_manifest] Removed uninvolved test: " + str(test))
            print("\n")
    for test_ in remove_tests:
        tests.remove(test_)
    return tests


def exec_query(endpoint_url: str, sparql: str, action,
               max_send: int = 4096) -> [None, Dict[str, Any]]:
    """
    Execute a single SPARQL query against the given endpoint
    """

    params = urllib.parse.urlencode({'query': sparql, 'send': max_send, 'action': action})
    url_suffix = '/?' + params

    print("exec_query = " + endpoint_url + url_suffix, flush=True)

    headers = {"User-Agent": "Mozilla/5.0"}
    # headers = {'Connection': 'close'}
    flag_passed = False
    while not flag_passed:
        try:
            s = requests.Session()
            retries = Retry(total=5,
                            backoff_factor=0.1,
                            status_forcelist=[500, 502, 503, 504])
            s.mount('http://', HTTPAdapter(max_retries=retries))

            response = s.get(url=endpoint_url + url_suffix, headers=headers, timeout=60)
            flag_passed = True
        except Exception as e:
            print(str(e))
            time.sleep(1)
            requests.session().close()

    print("response_reason = " + response.reason)
    print("response_statusCode = ", response.status_code)
    # responseJSON = response.json()
    # print("response_json = " + json.dumps(responseJSON), "\n", flush=True)
    # print("response_text = " + response.text, "\n", flush=True)
    requests.session().close()
    return response


'''
git submodule add https://github.com/w3c/rdf-tests.git

Folders in submodule:
    nquads/
    ns/
    ntriples/
    rdf-mt/
    rdf-xml/
    »» sparql11/ ««
    trig/
    turtle/ 

cd w3c/rdf-tests/sparql11/

ls | grep 'data'

    data-r2/        «««««« Sparql 1.0 Tests
    data-sparql11/  «««««« Sparql 1.1 Tests

'''


# defines what files in what directories to open
def must_open(dirnames, filename):
    if filename == 'manifest.ttl':
        return True
    else:
        return False


def opened_files(*args):
    """generate a sequence of pairs (path to file, opened file)
    in a given directory. Same arguments as os.walk."""
    for dirpath, dirnames, filenames in os.walk(*args):
        for filename in filenames:
            if must_open(dirnames, filename):
                dirname = Path(dirpath).name
                if dirname != 'data-r2' and dirname != 'data-sparql11':
                    filepath = os.path.join(dirpath, filename)
                    yield filepath, open(filepath, "r")


def enqueue_output(out, queue):
    for line in iter(out.readline, b''):
        queue.put(line)
    out.close()


if __name__ == '__main__':
    print("\nPython {:s} on {:s}\n".format(sys.version, platform.platform()))
    print('Number of arguments:', len(sys.argv), 'arguments.')
    print('Argument List:', str(sys.argv), '\n')

    if len(sys.argv) != 3:
        print("Usage: ", sys.argv[0], "<manifests_folders (rdf-tests)>  <Qlever_binary>")
        sys.exit(1)

    # Argument List: ['/mnt/c/Users/Joao/PycharmProjects/Qlever_Python/w3c_sparql1.1_benchmarking.py',
    #                 'manifests/'
    #                 '/mnt/c/Users/Joao/Desktop/Mestrado/ERASMUS/Winter Semester/git_joaomarques_qlever/qlever/']

    _manifests_dir = sys.argv[1]
    _qlever_binary = sys.argv[2]
    endpoint = 'http://localhost:9099'  # »» the endpoint port user-defined ««

    '''
    # https://github.com/RDFLib/rdflib
    # For normal 'ttl' files, not w3c-ttls
    
    from rdflib import Graph

    graph = Graph()
    graph.parse('myfile.ttl', format='ttl')
    for s, p, o in graph:
        print(s, p, o)
    '''

    '''
        **** Parse Manifests ****
    '''
    parsed_tests_map = []
    for filepath, fp_file in opened_files(_manifests_dir):
        print('Found manifest in: ' + filepath)
        print('Parsing.....')
        parsed_tests_map.append(parse_manifest(filepath, fp_file))
        print('Parsing %s done!\n' % filepath)

    # Save original working directory
    originalWorkDir = os.getcwd()

    # Build QLEVER if not yet build
    build = os.path.exists(_qlever_binary + "build/")
    if not build:
        os.mkdir(_qlever_binary + "build/")
        print("Cmaking the Server...")
        os.chdir(_qlever_binary + "build/")
        currentWorkDir = os.getcwd()
        print("currentWorkDir = " + currentWorkDir)
        cMakeCommand = "cmake -DCMAKE_BUILD_TYPE=Release -DLOGLEVEL=INFO -DUSE_PARALLEL=true -GNinja .. && ninja"
        print("cMakeCommand = " + cMakeCommand)
        cMakeProcess = subprocess.Popen(cMakeCommand, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        output, error = cMakeProcess.communicate()
        exit_code = cMakeProcess.wait()  # Wait until the cMakeProcess finishes to collect output/error
        if output:
            print("\nSubProcess output = " + str(output))
        if error:
            print("SubProcess error = " + str(error))

        # Check output/error/exit_code
        if exit_code != 0:
            print("Error! cMakeProcess exit_code = " + str(exit_code) + "\n")
        else:
            print("cMakeProcess finished properly\n")
        del output, error, exit_code

        os.chdir(_qlever_binary + "build/benchmark")
        currentWorkDir = os.getcwd()
        print("currentWorkDir = " + currentWorkDir, "\n")

    # Create benchmark directory and change current work directory to that new one
    if not os.path.exists(_qlever_binary + "build/benchmark/"):
        os.mkdir(_qlever_binary + "build/benchmark/")
    os.chdir(_qlever_binary + "build/benchmark/")
    currentWorkDir = os.getcwd()

    print("originalWorkDir = " + originalWorkDir)
    print("currentWorkDir = " + currentWorkDir)

    total_tests = total_tests_tmp = 0

    for parsed_manifest in parsed_tests_map:
        for test in parsed_manifest:
            total_tests_tmp += 1

    print("\n\t »»»»» Total expected tests = " + str(total_tests_tmp), "\n")


    '''
        **** Execute all parsed manifest-tests (Main Loop) ****
    '''
    for parsed_manifest in parsed_tests_map:
        for test in parsed_manifest:
            total_tests += 1
            actualTestName = test['name']

            print("\n*************************************************************************************************")
            print("*************************************************************************************************\n")
            print("\t »»» Current Test # ", total_tests, " =", str(test), "\n")


            test_type = test['type']
            type_name = list(test_type.values())[0]
            print("type_name = ", type_name)
            print("Test Action = ", str(test['actions']))
            print("Test Result = ", str(test['result']), "\n")

            request_not_empty = False
            flag_graph = False

            if len(test['actions']) == 0 or test['actions'] == '[]':
                print("Empty action")
                if len(test['request']) == 0:
                    continue
                else:
                    print("HTTP test")
                    print("\t>> Request-HTTP: ", test['request'])

            for index2, entry in enumerate(test['result']):
                if flag_graph:
                    break
                for name in entry:
                    if 'graph' in name:
                        flag_graph = True
                        break
            if flag_graph:
                print("result uses \'Graphs-data\' not supported by (current) Qlever\n")
                continue

            indexBuilderPos = -1

            for index1, entry in enumerate(test['actions']):
                for name in entry:
                    if 'graph' in name:
                        flag_graph = True
                        break
                    if 'data' in name:
                        request_not_empty = True
                        indexBuilderPos = index1
            if not request_not_empty:
                print("action does not have = \'data\'")
                print("Possibly does not require any initial data (empty) for IndexBuilder {not supported}\n")
                continue
            elif flag_graph:
                print("action uses \'Graphs-data\' not supported by (current) Qlever\n")
                continue


            # parsedActions = test['parsed_actions']
            # parsedResults = test['parsed_results']
            # concatInputFiles = test['concatInputFiles']
            # concatInputFiles = open(test['dir'] + "/" + test['actions'][1][1][1:-1], 'r').read()

            ''' 
                **** Mount Qlever-Index ****
            '''
            indexBuilderCommand = './../IndexBuilderMain -l -i ' \
                                  + actualTestName + \
                                  ' -F ttl ' + \
                                  '-f ' + test['dir'] + "/" + test['actions'][indexBuilderPos][1][1:-1] + \
                                  ' -s ' + _qlever_binary.replace(' ', '\ ') \
                                  + 'e2e/e2e-build-settings.json'  # generic build settings

            print("indexBuilderCommand = " + indexBuilderCommand)

            indexBuilderProcess = subprocess.Popen(indexBuilderCommand, shell=True,
                                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            '''
                (Self-)Terminate indexBuilder and catch all output
            '''
            output, error = indexBuilderProcess.communicate()
            if output:
                print("\nSubProcess output = " + str(output))
            if error:
                print("SubProcess error = " + str(error))
            exit_code = indexBuilderProcess.wait()  # Wait until the Index Builder finishes

            # Check output/error/exit_code
            if exit_code != 0:
                print("Error! indexBuilderProcess exit_code = " + str(exit_code) + "\n")  # Big Error
                continue
            else:
                print("indexBuilderProcess finished properly, continuing...\n")

            '''
               **** Launch Qlever-Server ****
            '''
            serverCommand = './../ServerMain -i ' + actualTestName + ' -p 9099 -m 1'
            print("serverCommand = " + serverCommand + "\n")

            serverProcess = subprocess.Popen(serverCommand, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            os.set_blocking(serverProcess.stdout.fileno(), False)

            # Connect to Server
            serverActive = False
            while not serverActive:
                a_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                location = ("", 9099)
                connection_check = a_socket.connect_ex(location)
                if connection_check == 0:
                    print("Port is open")
                    a_socket.close()
                    break
                else:
                    print("Port is not open")
                a_socket.close()
                print("Server not reached: new try in 3 seconds....")
                time.sleep(.5)  # Sleep 0.5 seconds


            # select the right entry-position
            query_index = -1
            if indexBuilderPos == 0:
                query_index = 1
            else:
                query_index = 0

            query_sparql = test['dir'] + "/" + test['actions'][query_index][1][1:-1]

            # Option A: Open One Request/Query File (if exists! -> query NOT EXPLICIT in manifest but pointed to a file)
            # Option B: HTTP-tests (query EXPLICIT in manifest) --> https://zetcode.com/python/getpostrequest/
            # Option C: Have a list of tests (more then 1 Request/Query file within the same test)
            # Option D: ...

            # Switch by option (test-contents)

            # Check which one (by test-content)
            ## Option A:
            with open(query_sparql, 'r') as file:
                data = file.read()

                print("\nAscii Request_data: " + ascii(data))
                print("Endpoint = " + endpoint)

                if isinstance(test['result'], list) and len(test['result']) == 1:
                    expected_file_data = test['dir'] + "/" + test['result'][0][0][1:-1]
                else:
                    expected_file_data = test['dir'] + "/" + test['result'][0][1:-1]

                file_result_suffix = expected_file_data[expected_file_data.rfind('.') + 1:]
                print("expected_result_file_data path = " + expected_file_data)

                if ".srj" in expected_file_data:
                    server_action = "sparql_json_export"
                elif ".srx" in expected_file_data:
                    server_action = "sparql_json_export"
                elif ".ttl" in expected_file_data:
                    server_action = "sparql_json_export"
                elif ".csv" in expected_file_data:
                    server_action = "csv_export"
                elif ".tsv" in expected_file_data:
                    server_action = "tsv_export"
                else:
                    1 == 1
                    print("\t »» expected_file_data suffix = **ELSE**")
                    server_action = "sparql_json_export"

                print("Action = " + server_action)

                # result = exec_query(endpoint_url=endpoint, sparql=ascii(data), action=server_action)
                sys.stdout.flush()
                result = exec_query(endpoint_url=endpoint, sparql=data, action=server_action)

                # update the test with the server-response
                test.update({"server-response": {result.reason, result.status_code, result.text}})

                time.sleep(.3)  # Wait 0.3 second for the Server to flush all STD_OUT/STD_ERR/STD_WRN

                print("server_answer = ", result.text, flush=True)


                errorTrace = None
                if server_action == "sparql_json_export":
                    result_JSON = result.json()
                    if result.status_code != 200:  # Not-OK
                        errorTrace = result_JSON['exception']
                        output_res = "query not answered;reason: " + str(result_JSON) + "; details: " + errorTrace
                    else:
                        # Comparing Tools
                        output_res = "query answered; result: " + str(result_JSON)

                    f = open("result_" + actualTestName + ".txt", "w")
                    f.write(output_res)
                    f.close()

                    # Multiple RESULTS FORMATS (convert if necessary with Apache-Jena ./riot)
                    # Options 1,2,3,...

                    if file_result_suffix == "srj":
                        ### Compare JSONs:   --> BNODES (!!)
                        with open(expected_file_data, 'r') as expected:
                            data_expected = expected.read()
                            data_expected = json.loads(data_expected)

                            f_expected = open("expected_" + actualTestName + ".txt", "w")
                            f_expected.write(json.dumps(data_expected, indent=4))
                            f_expected.close()

                            f_RAW_result = open("raw_result" + actualTestName + ".txt", "w")
                            f_RAW_result.write(json.dumps(result_JSON, indent=4))
                            f_RAW_result.close()

                            diff = jsoncomparison.Compare().check(data_expected, result_JSON)
                            f_compare = open("compare_" + actualTestName + ".txt", "w")
                            f_compare.write(json.dumps(diff, indent=4))
                            f_compare.close()
                    else:
                        1 == 1
                        print("\t »» file_result_suffix is * ", file_result_suffix, " *")

                elif server_action == "turtle_export":
                    1 == 1
                    print("\t »» server_action = turtle_export")
                elif server_action == "csv_export" or server_action == "tsv_export":
                    print("\t »» server_action = ", server_action)
                    with open(expected_file_data, 'r') as t1:
                        # , open(result.text, 'r') as t2:
                        fileone = t1.readlines()
                        # filetwo = t2.readlines()

                    buf = io.StringIO(result.text)

                    if server_action == "csv_export":
                        file_output = "compare_" + actualTestName + ".csv"
                    else:
                        file_output = "compare_" + actualTestName + ".tsv"
                    with open(file_output, 'w') as outFile:
                        for line in fileone:
                            if line not in buf.readline():
                                outFile.write(line)

                else:
                    1 == 1
                    print("\t »» server_action = **ELSE**")

            result.close()

            '''
                **** Terminate the Server and catch all output ****
            '''
            print("\nTerminating the server...\n")
            # Read the OUTPUT from Server
            sys.stdout.flush()
            start = time.time()
            while True:
                for i in range(2):
                    line = serverProcess.stdout.readline()
                    if len(line):
                        print(line)
                    # time.sleep(0.5)
                if time.time() > start + 2:
                    break

            serverProcess.terminate()

            # Wait until process terminates
            while serverProcess.poll() is None:
                time.sleep(0.5)
            print("\nServer terminated!")

            # Delete Current-Index Files (Garbage)
            for filename in glob.glob(_qlever_binary + "/build/benchmark/" + actualTestName + "*"):
                os.remove(filename)

            # Delete Remaining Garbage
            for filename in glob.glob(_qlever_binary + "/build/benchmark/*.disk"):
                os.remove(filename)


    '''
        After benchmark
    '''

    print("\nTOTAL manifests = " + str(len(parsed_tests_map)))
    print("TOTAL Parsed tests = " + str(total_tests))

    '''
        **** Save All Results in one file as well ****
    '''

    '''
    # tests (yaml/csv/tsv/json)
    # for each test:
    #   prepare indexBuilder/serverMain
    #   run()
    exec_tests(parsed_tests_map)  # *** parsed_tests_map.update({qlever_result: _qlever_results_map}) ***
    
    results = []
    for test in tests_map:
        results.append(create_output_results(test['label'], test['name'], test[result]))
    
    # write results to xlsx/html
    xlsx_results = print_results_xlsx(results)  ## xlsx
    html_results = print_results_html(xlsx_results)  ## html
    '''
