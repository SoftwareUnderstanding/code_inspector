"""Code Inspector
This script parses a file or files within directory
(and its subdirectories) to extract all the relevant information,
such as documentation, classes (and their methods), functions, etc.
To extract information from docstrings, we have started with the codes
documented.
This tool accepts (for now) only python code (.py)
This script requires `ast`, `cdmcfparser` and `docsting_parse`
be installed within the Python environment you are running 
this script in.
"""

import ast
import json
import os
import sys
import tokenize
import glob
import click
from cdmcfparser import getControlFlowFromFile
from docstring_parser import parse as docParse
from structure_tree import DisplayablePath, get_directory_structure
from staticfg import builder
from pathlib import Path
from unittest import mock
import setuptools
import tempfile
import subprocess
from json2html import *

class CodeInspection:
    def __init__(self, path, outCfPath, outJsonPath, flag_png):
        """ init method initiliazes the Code_Inspection object
        :param self self: represent the instance of the class
        :param str path: the file to inspect
        :param str outCfPath: the output directory to store the control flow information
        :param str outJsonPath: the output directory to store the json file with features extracted from the ast tree.
        :param int flag_png: flag to indicate to generate or not control flow figures
        """

        self.path = path
        self.flag_png = flag_png
        self.outJsonPath = outJsonPath
        self.outCfPath = outCfPath
        self.tree = self.parser_file()
        self.fileInfo = self.inspect_file()
        format = "png"
        self.controlFlowInfo = self.inspect_controlflow(format)
        self.funcsInfo = self.inspect_functions()
        self.classesInfo = self.inspect_classes()
        self.depInfo = self.inspect_dependencies()
        self.fileJson = self.file_json()

    def parser_file(self):
        """ parse_file method parsers a file as an AST tree
        :param self self: represent the instance of the class
        :return ast.tree: the file as an ast tree
        """

        with tokenize.open(self.path) as f:
            return ast.parse(f.read(), filename=self.path)

    def inspect_file(self):
        """ inspec_file method extracts the features at file level.
        Those features are path, fileNameBase, extension, docstring
	The method support several levels of docstrings extraction,
        such as file's long, short a full descrition.
        :param self self: represent the instance of the class
        :return dictionary a dictionary with the file information extracted
        """
        fileInfo = {}
        fileInfo["path"] = self.path
        fileName = os.path.basename(self.path).split(".")
        fileInfo["fileNameBase"] = fileName[0]
        fileInfo["extension"] = fileName[1]
        ds_m = ast.get_docstring(self.tree)
        docstring = docParse(ds_m)
        fileInfo["doc"] = {}
        fileInfo["doc"]["long_description"] = docstring.long_description if docstring.long_description else {}
        fileInfo["doc"]["short_description"] = docstring.short_description if docstring.short_description else {}
        fileInfo["doc"]["full"] = ds_m if ds_m else {}
        # fileInfo["doc"]["meta"]=docstring.meta if docstring.meta else {}
        return fileInfo

    def inspect_controlflow(self, format):
        """inspect_controlFlow uses two methods for 
        extracting the controlflow of a file. One as a
        text and another as a figure (PNG/PDF/DOT).   
        
        :param self self: represent the instance of the class
        :param str format: represent the format to save the figure
        :return dictionary: a dictionary with the all information extracted (at file level)
        """
        controlInfo = {}
        cfg = getControlFlowFromFile(self.path)
        cfg_txt = self._formatFlow(str(cfg))
        cfg_txt_file = self.outCfPath + "/" + self.fileInfo["fileNameBase"] + ".txt"

        with open(cfg_txt_file, 'w') as outfile:
            outfile.write(cfg_txt)
        controlInfo["cfg"] = cfg_txt_file

        if self.flag_png:
            cfg_visual = builder.CFGBuilder().build_from_file(self.fileInfo["fileNameBase"], self.path)
            cfg_path = self.outCfPath + "/" + self.fileInfo["fileNameBase"]
            cfg_visual.build_visual(cfg_path, format=format, calls=False, show=False)
            controlInfo["png"] = cfg_path + "." + format
            # delete the second file generated by the cfg_visual (not needed!)
            os.remove(cfg_path)
        else:
            controlInfo["png"] = "None"
        return controlInfo

    def inspect_functions(self):
        """ inspect_functions detects all the functions in a AST tree, and calls
        to _f_definitions method to extracts all the features at function level.
        :param self self: represent the instance of the class
        :return dictionary: a dictionary with the all functions information extracted
        """

        functions_definitions = [node for node in self.tree.body if isinstance(node, ast.FunctionDef)]
        return self._f_definitions(functions_definitions)

    def inspect_classes(self):
        """ inspect_classes detecs all the classes and their methods,
         and extracts their features. It also calls to _f_definitions method
        to extract features at method level.
        The features extracted are name, docstring (this information is further analysed
        and classified into several categories), extends, start
        and end of the line and methods.
        :param self self: represent the instance of the class
        :return dictionary: a dictionary with the all classes information extracted
        """

        classes_definitions = [node for node in self.tree.body if isinstance(node, ast.ClassDef)]
        classesInfo = {}
        for c in classes_definitions:
            classesInfo[c.name] = {}
            ds_c = ast.get_docstring(c)
            docstring = docParse(ds_c)
            classesInfo[c.name]["doc"] = {}
            classesInfo[c.name]["doc"][
                "long_description"] = docstring.long_description if docstring.long_description else {}
            classesInfo[c.name]["doc"][
                "short_description"] = docstring.short_description if docstring.short_description else {}
            classesInfo[c.name]["doc"]["full"] = ds_c if ds_c else {}
            # classesInfo[c.name]["doc"]["meta"]=docstring.meta if docstring.meta else {}

            try:
                classesInfo[c.name]["extend"] = [b.id for b in c.bases]
            except:
                try:
                    classesInfo[c.name]["extend"] = [
                        b.value.func.id if isinstance(b, ast.Call) and hasattr(b, 'value') else b.value.id if hasattr(b,
                                                                                                                      'value') else ""
                        for b in c.bases]
                except:
                    classesInfo[c.name]["extend"] = []

            classesInfo[c.name]["min_max_lineno"] = self._compute_interval(c)
            methods_definitions = [node for node in c.body if isinstance(node, ast.FunctionDef)]
            classesInfo[c.name]["methods"] = self._f_definitions(methods_definitions)
        return classesInfo

    def inspect_dependencies(self):
        """ inspect_dependencies method extracts the features at dependencies level.
        Those features are module , name, and alias.
        :param self self: represent the instance of the class
        :return dictionary: a dictionary with the all dependencies information extracted
        """

        depInfo = []
        for node in ast.iter_child_nodes(self.tree):
            if isinstance(node, ast.Import):
                module = []
            elif isinstance(node, ast.ImportFrom):
                try:
                    module = node.module.split('.')
                except:
                    module = []
            else:
                continue
            for n in node.names:
                current_dep = {"from_module": module,
                               "import": n.name.split('.'),
                               "alias": n.asname}
                depInfo.append(current_dep)

        return depInfo


   
    def _ast_if_main(self):
        """ method for getting if the file has a if __name__ == "__main__"
            and if it calls a method (e.g. main, version) or not. 
        :param self self: represent the instance of the class
        :return main_info : dictionary with a flag stored in "main_flag" (1 if the if __name__ == main is found, 0 otherwise) 
         and then "main_function" with the name of the function that is called.
        """
        
        if_main_definitions = [node for node in self.tree.body if isinstance(node, ast.If)]
        if_main_flag = 0 
        if_main_func = ""
        main_info={}
 
        for x in if_main_definitions:
            try:
                if x.test.comparators[0].s == "__main__" :
                    if_main_flag = 1 
            
                for i in x.body:
                    if i.value.func.id:
                        if_main_func = i.value.func.id
                break 
            except:
                pass

        main_info["main_flag"] = if_main_flag
        main_info["main_function"] = if_main_func
        return main_info

    def file_json(self):
        """file_json method aggregates all the features previously
        extracted from a given file such as, functions, classes 
        and dependencies levels into the same dictionary.
        
        It also writes this new dictionary to a json file.
        :param self self: represent the instance of the class
        :return dictionary: a dictionary with the all information extracted (at file level)
        """

        file_dict = {}
        file_dict["file"] = self.fileInfo
        file_dict["dependencies"] = self.depInfo
        file_dict["classes"] = self.classesInfo
        file_dict["functions"] = self.funcsInfo
        file_dict["controlflow"] = self.controlFlowInfo
        file_dict["main_info"] = self._ast_if_main()

        json_file = self.outJsonPath + "/" + self.fileInfo["fileNameBase"] + ".json"
        with open(json_file, 'w') as outfile:
            json.dump(prune_json(file_dict), outfile)
        return file_dict

    def _f_definitions(self, functions_definitions):
        """_f_definitions extracts the name, args, doscstring 
        returns, raises of a list of functions or a methods.
        Furthermore, it also extracts automatically several values
        from a docstring, such as long and short description, arguments' 
        name, description, type, default values and if it they are optional
        or not. 
        :param self self: represent the instance of the class
        :param list functions_definitions: represent a list with all functions or methods nodes
        :return dictionary: a dictionary with the all the information at function/method level
        """

        funcsInfo = {}
        for f in functions_definitions:
            funcsInfo[f.name] = {}
            ds_f = ast.get_docstring(f)
            docstring = docParse(ds_f)
            funcsInfo[f.name]["doc"] = {}
            funcsInfo[f.name]["doc"][
                "long_description"] = docstring.long_description if docstring.long_description else {}
            funcsInfo[f.name]["doc"][
                "short_description"] = docstring.short_description if docstring.short_description else {}
            funcsInfo[f.name]["doc"]["args"] = {}
            for i in docstring.params:
                funcsInfo[f.name]["doc"]["args"][i.arg_name] = {}
                funcsInfo[f.name]["doc"]["args"][i.arg_name]["description"] = i.description
                funcsInfo[f.name]["doc"]["args"][i.arg_name]["type_name"] = i.type_name
                funcsInfo[f.name]["doc"]["args"][i.arg_name]["is_optional"] = i.is_optional
                funcsInfo[f.name]["doc"]["args"][i.arg_name]["default"] = i.default
            if docstring.returns:
                r = docstring.returns
                funcsInfo[f.name]["doc"]["returns"] = {}
                funcsInfo[f.name]["doc"]["returns"]["description"] = r.description
                funcsInfo[f.name]["doc"]["returns"]["type_name"] = r.type_name
                funcsInfo[f.name]["doc"]["returns"]["is_generator"] = r.is_generator
                funcsInfo[f.name]["doc"]["returns"]["return_name"] = r.return_name
            funcsInfo[f.name]["doc"]["raises"] = {}
            for num, i in enumerate(docstring.raises):
                funcsInfo[f.name]["doc"]["raises"][num] = {}
                funcsInfo[f.name]["doc"]["raises"][num]["description"] = i.description
                funcsInfo[f.name]["doc"]["raises"][num]["type_name"] = i.type_name

            funcsInfo[f.name]["args"] = [a.arg for a in f.args.args]
            rs = [node for node in ast.walk(f) if isinstance(node, (ast.Return,))]
            funcsInfo[f.name]["returns"] = [self._get_ids(r.value) for r in rs]
            funcsInfo[f.name]["min_max_lineno"] = self._compute_interval(f)
        return funcsInfo

    def _get_ids(self, elt):
        """_get_ids extracts identifiers if present. 
         If not return None
        :param self self: represent the instance of the class
        :param ast.node elt: AST node
        :return list: list of identifiers
        """
        if isinstance(elt, (ast.List,)) or isinstance(elt, (ast.Tuple,)):
            # For tuple or list get id of each item if item is a Name
            return [x.id for x in elt.elts if isinstance(x, (ast.Name,))]
        if isinstance(elt, (ast.Name,)):
            return [elt.id]

    def _compute_interval(self, node):
        """_compute_interval extract the lines (min and max)
         for a given class, function or method.
        :param self self: represent the instance of the class
        :param ast.node node: AST node
        :return set: min and max lines
        """
        min_lineno = node.lineno
        max_lineno = node.lineno
        for node in ast.walk(node):
            if hasattr(node, "lineno"):
                min_lineno = min(min_lineno, node.lineno)
                max_lineno = max(max_lineno, node.lineno)
        return {"min_lineno": min_lineno, "max_lineno": max_lineno + 1}

    def _formatFlow(self, s):
        """_formatFlow reformats the control flow output
        as a text.
        :param self self: represent the instance of the class
        :param cfg_graph s: control flow graph 
        :return str: cfg formated as a text
        """

        result = ""
        shifts = []  # positions of opening '<'
        pos = 0  # symbol position in a line
        nextIsList = False

        def IsNextList(index, maxIndex, buf):
            if index == maxIndex:
                return False
            if buf[index + 1] == '<':
                return True
            if index < maxIndex - 1:
                if buf[index + 1] == '\n' and buf[index + 2] == '<':
                    return True
            return False

        maxIndex = len(s) - 1
        for index in range(len(s)):
            sym = s[index]
            if sym == "\n":
                lastShift = shifts[-1]
                result += sym + lastShift * " "
                pos = lastShift
                if index < maxIndex:
                    if s[index + 1] not in "<>":
                        result += " "
                        pos += 1
                continue
            if sym == "<":
                if nextIsList == False:
                    shifts.append(pos)
                else:
                    nextIsList = False
                pos += 1
                result += sym
                continue
            if sym == ">":
                shift = shifts[-1]
                result += '\n'
                result += shift * " "
                pos = shift
                result += sym
                pos += 1
                if IsNextList(index, maxIndex, s):
                    nextIsList = True
                else:
                    del shifts[-1]
                    nextIsList = False
                continue
            result += sym
            pos += 1
        return result


def create_output_dirs(output_dir):
    """create_output_dirs creates two subdirectories
       to save the results. ControlFlow to save the
       cfg information (txt and PNG) and JsonFiles to
       save the aggregated json file with all the information
       extracted per file. 
       :param str output_dir: Output Directory in which the new subdirectories
                          will be created.
       """

    control_flow_dir = output_dir + "/ControlFlow"

    if not os.path.exists(control_flow_dir):
        print("Creating cf %s" % control_flow_dir)
        os.makedirs(control_flow_dir)
    else:
        pass
    jsonDir = output_dir + "/JsonFiles"

    if not os.path.exists(jsonDir):
        print("Creating jsDir:%s" % jsonDir)
        os.makedirs(jsonDir)
    else:
        pass
    return control_flow_dir, jsonDir


@click.command()
@click.option('-i', '--input_path', type=str, required=True, help="input path of the file or directory to inspect.")
@click.option('-f', '--fig', type=bool, is_flag=True, help="activate the control_flow figure generator.")
@click.option('-o', '--output_dir', type=str, default="OutputDir", 
              help="output directory path to store results. If the directory does not exist, the tool will create it.")
@click.option('-ignore_dir', '--ignore_dir_pattern', multiple=True, default=[".", "__pycache__"], 
              help="ignore directories starting with a certain pattern. This parameter can be provided multiple times to ignore multiple directory patterns.")
@click.option('-ignore_file', '--ignore_file_pattern', multiple=True, default=[".", "__pycache__"], 
              help="ignore files starting with a certain pattern. This parameter can be provided multiple times to ignore multiple file patterns.")

@click.option('-r', '--requirements', type=bool, is_flag=True, help="find the requirements of the repository.")

@click.option('-html', '--html_output', type=bool, is_flag=True, help="generates an html file of the DirJson in the output directory.")

def main(input_path, fig, output_dir, ignore_dir_pattern, ignore_file_pattern, requirements, html_output):
    if (not os.path.isfile(input_path)) and (not os.path.isdir(input_path)):
        print('The file or directory specified does not exist')
        sys.exit()

    if os.path.isfile(input_path):
        cf_dir, json_dir = create_output_dirs(output_dir)
        code_info = CodeInspection(input_path, cf_dir, json_dir, fig)

    else:
        dir_info = {}
        for subdir, dirs, files in os.walk(input_path):
            
            for ignore_d in ignore_dir_pattern:
                dirs[:] = [d for d in dirs if not d.startswith(ignore_d)]
            
            for ignore_f in ignore_dir_pattern:
                files = [f for f in files if not f.startswith(ignore_f)]
            for f in files:
                if ".py" in f and not f.endswith(".pyc"):
                    try:
                        path = os.path.join(subdir, f)
                        out_dir = output_dir + "/" + os.path.basename(subdir)
                        cf_dir, json_dir = create_output_dirs(out_dir)
                        code_info = CodeInspection(path, cf_dir, json_dir, fig)
                        if out_dir not in dir_info:
                            dir_info[out_dir] = [code_info.fileJson]
                        else:
                            dir_info[out_dir].append(code_info.fileJson)
                    except:
                        print("Error when processing "+f+": ", sys.exc_info()[0])
                        continue

        #Note:1 for visualising the tree, nothing or 0 for not.
        dir_tree=directory_tree(input_path, 1)
        if requirements:
            dir_requirements=find_requirements(input_path)
            dir_info["requirements"]= dir_requirements
        dir_info["dir_tree"]=dir_tree
        dir_info["dir_type"]=directory_type(dir_info, input_path)
        json_file = output_dir + "/DirectoryInfo.json"
        pruned_json = prune_json(dir_info)
        with open(json_file, 'w') as outfile:
            json.dump(pruned_json, outfile)
        print_summary(dir_info)
        if html_output:
             output_file_html= output_dir + "/DirectoryInfo.html"
             generate_output_html(pruned_json, output_file_html)



def print_summary(json_dict):
    """
    This method prints a small summary of the classes and properties recognized during the analysis.
    At the moment this method is only invoked when a directory with multiple files is passed.
    """
    folders = 0
    files = 0
    dependencies = 0
    functions = 0
    classes = 0
    for key, value in json_dict.items():
        if "/" in key:
            folders += 1
        if isinstance(value, list):
            for element in value:
                files += 1
                if element["dependencies"]:
                    dependencies += len(element["dependencies"])
                if element["functions"]:
                    functions += len(element["functions"])
                if element["classes"]:
                    classes += len(element["classes"])
    print("Analysis completed")
    print("Total number of folders processed (root folder is considered a folder):", folders)
    print("Total number of files found: ", files)
    print("Total number of classes found: ", classes)
    print("Total number of dependencies found in those files", dependencies)
    print("Total number of functions parsed: ", functions)


def prune_json(json_dict):
    """
    Method that given a JSON object, removes all its empty fields.
    This method simplifies the resultant JSON.
    :param json_dict input JSON file to prune
    :return JSON file removing empty values
    """
    final_dict = {}
    if not (isinstance(json_dict, dict)):
        # Ensure the element provided is a dict
        return json_dict
    else:
        for a, b in json_dict.items():
            if b:
                if isinstance(b, dict):
                    aux_dict = prune_json(b)
                    if aux_dict: # Remove empty dicts
                        final_dict[a] = aux_dict
                elif isinstance(b, list):
                    aux_list = list(filter(None, [prune_json(i) for i in b]))
                    if len(aux_list) >0: # Remove empty lists
                        final_dict[a] = aux_list
                else:
                    final_dict[a] = b
    return final_dict


def directory_tree(input_path, visual=0): 
    ignore_set = ('.git', '__pycache__')
    if visual:
        paths = DisplayablePath.make_tree(Path(input_path), criteria=lambda path: True if path.name not in ignore_set and not os.path.join("./", path.name).endswith(".pyc") else False)
        for path in paths:
            print(path.displayable())
    
    dir=get_directory_structure(input_path, ignore_set)
    return dir


def inspect_setup(parent_dir):
    setup_info={}
    sys.path.insert(0, parent_dir)
    current_dir = os.getcwd()
    os.chdir(parent_dir)
    with tempfile.NamedTemporaryFile(prefix="setup_temp_", mode='w', dir=parent_dir, suffix='.py') as temp_fh:
        with open(os.path.join(parent_dir, "setup.py"), 'r') as setup_fh:
            temp_fh.write(setup_fh.read())
            temp_fh.flush()
        try:
            with mock.patch.object(setuptools, 'setup') as mock_setup:
                module_name = os.path.basename(temp_fh.name).split(".")[0]
                __import__(module_name)
        except:
            package_name=subprocess.getoutput("python setup.py --name")
            os.chdir(current_dir)
            setup_info["type"]="package"
            setup_info["installation"] = "pip install " + package_name
            setup_info["run"] = ""+ package_name + " --help"
            return setup_info
        finally:
            # need to blow away the pyc
            try:
                os.remove("%sc"%temp_fh.name)
            except:
                pass
        args, kwargs = mock_setup.call_args
        package_name = kwargs.get('name', "")
        os.chdir(current_dir)
        if "console_scripts" in sorted(kwargs.get('entry_points', [])):
            setup_info["type"]="package"
            setup_info["installation"] = "pip install " + package_name
            setup_info["run"] = ""+ package_name + " --help"
            return setup_info
            
        else:
            setup_info["type"]="library"
            setup_info["installation"] = "pip install " + package_name
            setup_info["run"] = "import "+ package_name 
            return setup_info
            


def directory_type(dir_info, input_path):

   dir_type_info={}

   for dir in dir_info["dir_tree"]:
       for elem in dir_info["dir_tree"][dir]:
          if "setup.py" == elem or "setup.cfg" == elem : 
                  dir_type_info=inspect_setup(input_path)
                  return dir_type_info

   for key in dir_info:
       for elem in dir_info[key]:
           try:
              for dep in elem["dependencies"]:
                   for import_dep in dep["import"]:
                        if ("Flask" in import_dep) or ("flask" in import_dep) or ("flask_restful" in import_dep):
                                return "service"
                   for from_mod_dep in dep["from_module"]:
                        if ("Flask" in from_mod_dep) or ("flask" in from_mod_dep) or ("flask_restful" in from_mod_dep):
                                dir_type_info["type"]="service"
           except:
              pass
   
   # storing all the mains detected
   # and returning them all 
   main_files=[]  
   for key in dir_info:
       for elem in dir_info[key]:
           if "main_info" in elem:
                   if elem["main_info"]["main_flag"]:
                       main_files.append(elem["file"]["path"])
  
   for m in range(0, len(main_files)):
       dir_type_info[m]={}
       dir_type_info[m]["type"]="script with main" 
       dir_type_info[m]["run"]= "python " + main_files[m]  + " --help"
   return dir_type_info 
   
   python_files=[]
   for dir in dir_info["dir_tree"]:
       for elem in dir_info["dir_tree"][dir]:
           print("elem is %s" % elem)
           if ".py" in elem:
               python_files.append(elem)
   for f in range(0, len(python_files)):
       dir_type_info[f]={}
       dir_type_info[f]["type"]="script without main" 
       dir_type_info[f]["run"]="python " + python_files[f]  + " --help"
   return dir_type_info



def find_requirements(input_path):
        print("Finding the requirements with PIGAR for %s" %input_path)
        try:
           file_name= 'requirements_'+ os.path.basename(input_path) +'.txt'

           #Atention: we can modify the output of pigar, if we use echo N.
           #Answering yes (echo y), we allow for searching PyPI 
           #for the missing modules and filter some unnecessary modules. 

           cmd='echo y | pigar -P ' + input_path + ' --without-referenced-comments -p '+ file_name 
           #print("cmd: %s" %cmd)
           proc=subprocess.Popen(cmd.encode('utf-8'), shell=True, stdin=subprocess.PIPE,
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE)
           stdout, stderr = proc.communicate()
           reqDict={}
           with open(file_name, "r") as file:
               lines = file.readlines()[1:]
           file.close()
           for line in lines:
               try:
                   if line!="\n":
                       splitLine = line.split(" == ")
                       reqDict[splitLine[0]]=splitLine[1].split("\n")[0]
               except:
                    pass 
           #Atention: I am deleting the requirements file created by Pigar.
           #in the future we might want to keep it (just comenting the line bellow)
           os.system('rm ' + file_name)
           return reqDict

        except:
             print("Error finding the requirements in" % input_path)

def generate_output_html(pruned_json, output_file_html):
    """ Very basic html page - we can improve it later 
    """
    html=json2html.convert(json = pruned_json)
    
    with open(output_file_html, "w") as ht:
        ht.write(html)

if __name__ == "__main__":
    main()
