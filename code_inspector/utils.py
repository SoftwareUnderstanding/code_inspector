import ast
import os
import subprocess
from pathlib import Path

from json2html import *

from code_inspector.parse_setup_files import inspect_setup
from code_inspector.structure_tree import DisplayablePath, get_directory_structure


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
                if "dependencies" in element:
                    dependencies += len(element["dependencies"])
                if "functions" in element:
                    functions += len(element["functions"])
                if "classes" in element:
                    classes += len(element["classes"])
    print("Analysis completed")
    print("Total number of folders processed (root folder is considered a folder):", folders)
    print("Total number of files found: ", files)
    print("Total number of classes found: ", classes)
    print("Total number of dependencies found in those files", dependencies)
    print("Total number of functions parsed: ", functions)


def extract_directory_tree(input_path, ignore_dirs, ignore_files, visual=0):
    """
    Method to obtain the directory tree of a repository.
    The ignored directories and files that were inputted are also ignored.
    :input_path path of the repo to
    """
    ignore_set = ['.git', '__pycache__', '.idea', '.pytest_cache']
    ignore_set = tuple(list(ignore_dirs) + list(ignore_files) + ignore_set)
    if visual:
        paths = DisplayablePath.make_tree(Path(input_path), criteria=lambda
            path: True if path.name not in ignore_set and not os.path.join("../", path.name).endswith(".pyc") else False)
        for path in paths:
            print(path.displayable())
    return get_directory_structure(input_path, ignore_set)


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
            if b or isinstance(b, bool):
                if isinstance(b, dict):
                    aux_dict = prune_json(b)
                    if aux_dict:  # Remove empty dicts
                        final_dict[a] = aux_dict
                elif isinstance(b, list):
                    aux_list = list(filter(None, [prune_json(i) for i in b]))
                    if len(aux_list) > 0:  # Remove empty lists
                        final_dict[a] = aux_list
                else:
                    final_dict[a] = b
    return final_dict


def extract_requirements(input_path):
    print("Finding the requirements with the pigar package for %s" % input_path)
    try:
        file_name = 'requirements_' + os.path.basename(input_path) + '.txt'

        # Attention: we can modify the output of pigar, if we use echo N.
        # Answering yes (echo y), we allow searching for PyPI
        # for the missing modules and filter some unnecessary modules.

        # cmd = 'echo y | pigar -P ' + input_path + ' --without-referenced-comments -p ' + file_name
        cmd = 'echo n | pigar -P ' + input_path + ' --without-referenced-comments -p ' + file_name
        # print("cmd: %s" %cmd)
        proc = subprocess.Popen(cmd.encode('utf-8'), shell=True, stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = proc.communicate()
        req_dict = {}
        with open(file_name, "r") as file:
            lines = file.readlines()[1:]
        file.close()
        for line in lines:
            try:
                if line != "\n":
                    splitLine = line.split(" == ")
                    req_dict[splitLine[0]] = splitLine[1].split("\n")[0]
            except:
                pass
        # Note: Pigar requirement file is being deleted
        # in the future we might want to keep it (just commenting the line bellow)
        os.system('rm ' + file_name)
        return req_dict

    except:
        print("Error finding the requirements in" % input_path)


def extract_software_invocation(dir_info, dir_tree_info, input_path, call_list, readme):
    """
    Method to detect the directory type of a software project. This method also detects tests
    We distinguish four main types: script, package, library and service. Some can be more than one.
    :dir_info json containing all the extracted information about the software repository
    :dir_tree_info json containing the directory information of the target repo
    :input_path path of the repository to analyze
    :call_list json file containing the list of calls per file and functions or methods.
    :readme content of the readme file of the project (if any)
    """

    software_invocation_info = []
    setup_files = ("setup.py", "setup.cfg")
    server_dependencies = ("flask", "flask_restful", "falcon", "falcon_app", "aiohttp", "bottle", "django", "fastapi",
                           "locust", "pyramid", "hug", "eve", "connexion")

    # Note: other server dependencies are missing here. More testing is needed.
    flag_package_library = 0
    for directory in dir_tree_info:
        for elem in setup_files:  # first check setup.py, then cfg
            if elem in dir_tree_info[directory]:
                # 1. Exploration for package or library
                software_invocation_info.append(inspect_setup(input_path, elem))
                flag_package_library = 1
                break
                # We continue exploration to make sure we continue exploring mains even after detecting this is a
                # library

    # Looping across all mains
    # to decide if it is a service (main + server dep) or just a script (main without server dep)
    main_files = []

    # new list to store the "mains that have been previously classified as "test".
    test_files = []

    # new list to store files without mains
    body_only_files = []
    flag_service_main = 0
    for key in dir_info:  # filter (lambda key: key not in "directory_tree", dir_info):
        for elem in dir_info[key]:
            # TO DO: Determine here if the file is a test.
            # 1) Imports and uses functions that have asserts/testing frameworks. Example: pycg
            # 2) Uses functions that have asserts. Example: pyLODE.
            # Looking at framework/main is not enough. Test files can be "non-executable" (if they don't have a main)?

            # Check if the file is a test. Test files may not be executable (pytest may be run externally)
            is_test = False
            for cl in elem["classes"].values():
                for method in cl["methods"].values():
                    if any("assert" in call for call in method["calls"]):
                        is_test = True
                        break
            if not is_test:
                for f in elem["functions"].values():
                    if "assert" in f["calls"]:
                        is_test = True
            # if not is_test:
                #Check body (TO DO)
            if is_test:
                test_files.append(elem["file"]["path"])

            if elem["main_info"]["main_flag"]:
                flag_main_service = 0
                main_stored = 0
                try:
                    # 2. Exploration for services in files with "mains"
                    flag_service, software_invocation_info = service_check(elem, software_invocation_info,
                                                                           server_dependencies, "main", readme)
                except:
                    if elem["main_info"]["type"] != "test" and elem["main_info"]["type"] not in test_files:
                        main_files.append(elem["file"]["path"])
                    else:
                        test_files.append(elem["file"]["path"])
                        main_stored = 1

                if flag_service:
                    flag_service_main = 1

                if not flag_service and not main_stored:
                    if elem["main_info"]["type"] != "test":
                        main_files.append(elem["file"]["path"])
                    # else:
                    #     test_files.append(elem["file"]["path"])
            else:
                # NEW: Filtering only files with body
                if elem['body']['calls']: # and not in test files.
                    body_only_files.append(elem)

    m_secondary = [0] * len(main_files)
    flag_script_main = 0

    # this list (of lists) stores the mains that each main import
    import_mains = []
   
    # this list (of lists) stores the mains that each main is imported by
    imported_by = [None]*len(main_files)

    # 3. Exploration for main scripts
    for m in range(0, len(main_files)):
        m_calls = find_file_calls(main_files[m], call_list)
        # HERE I STORE WHICH OTHER MAIN FILES CALLS EACH "M" MAIN_FILE
        m_imports = extract_relations(main_files[m], m_calls, main_files, call_list)
      
        # storing those m_imports in the import_mains[m]
        import_mains.append(m_imports)
      
        for m_i in m_imports:
            m_secondary[main_files.index(m_i)] = 1

            if not imported_by[main_files.index(m_i)]:
                imported_by[main_files.index(m_i)] = []
            imported_by[main_files.index(m_i)].append(main_files[m])

    for m in range(0, len(main_files)):
        soft_info = {"type": "script", "run": "python " + main_files[m], "has_structure": "main",
                     "mentioned_in_readme": os.path.basename(os.path.normpath(main_files[m])) in readme,
                     "imports": import_mains[m], "imported_by": imported_by[m]}
        software_invocation_info.append(soft_info)
        flag_script_main = 1

    # tests with main. # TO DO: NOW TESTS WITH NO MAIN ARE RECOGNIZED.
    for t in range(0, len(test_files)):
        # Test files do not have help, they are usually run by themselves
        soft_info = {"type": "test", "run": "python " + test_files[t], "has_structure": "main",
                     "mentioned_in_readme": os.path.basename(os.path.normpath(test_files[t])) in readme}
        software_invocation_info.append(soft_info)

    flag_service_body = 0
    flag_script_body = 0
    for elem in body_only_files:
        # 4. Exploration for services in files with body 
        flag_service, software_invocation_info = service_check(elem, software_invocation_info,
                                                               server_dependencies, "body", readme)
        if flag_service:
            flag_service_body = 1

        # Only adding this information if we haven't not found libraries, packages, services or scripts with mains.
        # 5. Exploration for script without main in files with body 
        if not flag_service_main and not flag_service_body and not flag_package_library and not flag_script_main:
            soft_info = {"type": "script", "run": "python " + elem["file"]["path"], "has_structure": "body",
                         "mentioned_in_readme": elem["file"]["fileNameBase"] + "." + elem["file"][
                             "extension"] in readme}
            software_invocation_info.append(soft_info)
            flage_script_body = 1

    # Only adding this information if we haven't not found libraries, packages, services or scripts with mains
    # or bodies.
    # 6.  Exploration for script without main or body in files with body
    if not flag_script_body and not flag_service_main and not flag_service_body and not flag_package_library \
            and not flag_script_main:
        python_files = []
        for directory in dir_tree_info:
            for elem in dir_tree_info[directory]:
                if ".py" in elem:
                    python_files.append(os.path.abspath(input_path + "/" + directory + "/" + elem))

        for f in range(0, len(python_files)):
            soft_info = {"type": "script without main", "import": python_files[f], "has_structure": "without_body",
                         "mentioned_in_readme": os.path.basename(os.path.normpath(python_files[f])) in readme}
            software_invocation_info.append(soft_info)

    return software_invocation_info



def generate_output_html(pruned_json, output_file_html):
    """
    Method to generate a simple HTML view of the obtained JSON.
    :pruned_json JSON to print out
    :output_file_html path where to write the HTML
    """
    html = json2html.convert(json=pruned_json)

    with open(output_file_html, "w") as ht:
        ht.write(html)


def top_level_functions(body):
    return (f for f in body if isinstance(f, ast.FunctionDef))


def top_level_classes(body):
    return (c for c in body if isinstance(c, ast.ClassDef))


def parse_module(filename):
    with open(filename, "rt") as file:
        return ast.parse(file.read(), filename=filename)


def list_functions_classes_from_module(m, path):
    functions_classes = []

    try:
        # to open a module inside a directory
        m = m.replace(".", "/")
        repo_path = Path(path).parent.absolute()
        abs_repo_path = os.path.abspath(repo_path)
        file_module = abs_repo_path + "/" + m + ".py"
        tree = parse_module(file_module)
        for func in top_level_functions(tree.body):
            functions_classes.append(func.name)

        for cl in top_level_classes(tree.body):
            functions_classes.append(cl.name)

        type = "internal"
    except:
        
        #module = __import__(m)
        #functions = dir(module)
        type = "external"
    return functions_classes, type


def type_module(m, i, path):
    repo_path = Path(path).parent.absolute()
    abs_repo_path = os.path.abspath(repo_path)
    if m:
        m = m.replace(".", "/")
        file_module = abs_repo_path + "/" + m + "/" + i + ".py"
    else:
        file_module = abs_repo_path + "/" + i + ".py"
    file_module_path = Path(file_module)
    if file_module_path.is_file():
        return "internal"
    else:
        return "external"


def extract_call_functions(funcs_info, body=0):
    call_list = {}
    if body:
        if funcs_info["body"]["calls"]:
            call_list["local"] = funcs_info["body"]["calls"]
    else:
        for funct in funcs_info:
            if funcs_info[funct]["calls"]:
                call_list[funct] = {}
                call_list[funct]["local"] = funcs_info[funct]["calls"]
                if funcs_info[funct]["functions"]:
                    call_list[funct]["nested"] = extract_call_functions(funcs_info[funct]["functions"])
    return call_list


def extract_call_methods(classes_info):
    call_list = {}
    for method in classes_info:
        if classes_info[method]["calls"]:
            call_list[method] = {}
            call_list[method]["local"] = classes_info[method]["calls"]
            if classes_info[method]["functions"]:
                call_list[method]["nested"] = extract_call_methods(classes_info[method]["functions"])
    return call_list


def call_list_file(code_info):
    call_list = {}
    call_list["functions"] = extract_call_functions(code_info.funcsInfo)
    call_list["body"] = extract_call_functions(code_info.bodyInfo, body=1)
    for class_n in code_info.classesInfo:
        call_list[class_n] = extract_call_methods(code_info.classesInfo[class_n]["methods"])
    return call_list


def call_list_dir(dir_info):
    call_list = {}
    for dir in dir_info:
        call_list[dir] = {}
        for file_info in dir_info[dir]:
            file_path = file_info["file"]["path"]
            call_list[dir][file_path] = extract_call_functions(file_info["functions"])
            for class_n in file_info["classes"]:
                call_list[dir][file_path][class_n] = extract_call_methods(file_info["classes"][class_n]["methods"])
    return call_list


def find_file_calls(file_name, call_list):
    for dir in call_list:
        for elem in call_list[dir]:
            if elem in file_name:
                return call_list[dir][elem]


def find_module_calls(module, call_list):
    for dir in call_list:
        for elem in call_list[dir]:
            if "/"+module+"." in elem:
                #print("---MODULE %s, elem %s, giving call_list[%s][%s]" %(module, elem, dir, elem))
                return call_list[dir][elem]

            # DFS algorithm - Allowing up to 2 levels of depth.


def file_in_call(base, call, file, m_imports, call_list, orig_base, level):
    ### NOTE: LEVEL is a parameter very important here!
    ### It allows us to track how deep we are inside the recursivity search.

    ### If we want to modify the depth of the recursity, we just need to change the level_depth.
    level_depth = 2

    ## For each call, we extract all its sub_calls (level 1), 
    ## and for each sub_call we extract all its sub_sub_calls (level 2)  
    #### 

    if base in call and m_imports.count(file) == 0 and orig_base not in call:
        m_imports.append(file)
        return 1
    elif orig_base in call:
        return 0

    elif level < level_depth and call!="":
        m_calls_extern = {}
        module_base = call.split(".")[0]
        module_base = module_base + "."
        m_calls_extern = find_module_calls(module_base, call_list)
        # Note: Here is when we increase the level of recursivity
        level += 1
        if m_calls_extern:
            for m_c in m_calls_extern:
                flag_found = extract_data(base, m_calls_extern[m_c], file, m_imports, 0, call_list, orig_base, level)
                if flag_found:
                    return 1
        return 0
    else:
        return 0


def extract_local_function(base, m_calls_local, file, m_imports, flag_found, call_list, orig_base, level):
    for call in m_calls_local:
        flag_found = file_in_call(base, call, file, m_imports, call_list, orig_base, level)
        if flag_found:
            return flag_found
    return flag_found


def extract_nested_function(base, m_calls_nested, file, m_imports, flag_found, call_list, orig_base, level):
    for call in m_calls_nested:
        flag_found = extract_data(base, m_calls_nested, file, m_imports, flag_found, call_list, orig_base, level)
        if flag_found:
            return flag_found
    return flag_found


def extract_data(base, m_calls, file, m_imports, flag_found, call_list, orig_base, level):
    for elem in m_calls:
        if elem == "local":
            flag_found = extract_local_function(base, m_calls[elem], file, m_imports, flag_found, call_list, orig_base,
                                                level)
        elif elem == "nested":
            flag_found = extract_nested_function(base, m_calls[elem], file, m_imports, flag_found, call_list, orig_base,
                                                 level)
        else:
            flag_found = extract_data(base, m_calls[elem], file, m_imports, flag_found, call_list, orig_base, level)
        if flag_found:
            return flag_found
    return flag_found


# We will apply the DFS strategy later to find the external relationships.

def extract_relations(file_name, m_calls, main_files, call_list):
    m_imports = []
    orig_base = os.path.basename(file_name)
    orig_base = os.path.splitext(orig_base)[0]
    orig_base = orig_base + "."
    for file in main_files:
        if file not in file_name:
            flag_found = 0
            base = os.path.basename(file)
            base = os.path.splitext(base)[0]
            base = base + "."
            for m_c in m_calls:
                level = 0
                flag_found = extract_data(base, m_calls[m_c], file, m_imports, flag_found, call_list, orig_base, level)
                if flag_found:
                    return m_imports

    return m_imports


def service_check(elem, software_invocation_info, server_dependencies, has_structure, readme):
    flag_service = 0
    for dep in elem["dependencies"]:
        imports = dep["import"]
        flag_service, software_invocation_info = service_in_set(imports, server_dependencies, elem,
                                                                software_invocation_info, has_structure, readme)
        if flag_service:
            return flag_service, software_invocation_info
        else:
            modules = dep["from_module"]
            flag_service, software_invocation_info = service_in_set(modules, server_dependencies, elem,
                                                                    software_invocation_info, has_structure, readme)
            if flag_service:
                return flag_service, software_invocation_info
    return flag_service, software_invocation_info


def service_in_set(data, server_dependencies, elem, software_invocation_info, has_structure, readme):
    flag_service = 0
    if isinstance(data, list):
        for data_dep in data:
            if data_dep.lower() in server_dependencies:
                soft_info = {"type": "service", "run": "python " + elem["file"]["path"],
                             "has_structure": has_structure,
                             "mentioned_in_readme": elem["file"]["fileNameBase"] + "." + elem["file"][
                                 "extension"] in readme}
                flag_service = 1
                if soft_info not in software_invocation_info:
                    software_invocation_info.append(soft_info)
    else:
        if data:
            if data.lower() in server_dependencies:
                soft_info = {"type": "service", "run": "python " + elem["file"]["path"],
                             "has_structure": has_structure,
                             "mentioned_in_readme": elem["file"]["fileNameBase"] + "." + elem["file"][
                                 "extension"] in readme}
                flag_service = 1
                if soft_info not in software_invocation_info:
                    software_invocation_info.append(soft_info)
    return flag_service, software_invocation_info


def rank_software_invocation(soft_invocation_info_list):
    """
    Function to create a ranking over the different ways of executing a program.
    If two elements have the same position in the ranking, it means that there is no priority among them.
    Heuristic to order the invocation list is as follows, in decreasing order of prioritization:
        - If package or library is detected, this will be always first.
        - If something (script or service) is mentioned in the readme file, it is considered a priority.
        - Services are prioritized over scripts
        - Scripts with main are prioritized over script with body.
        - Scripts with body are prioritized over scripts with no body.
        TO DOs:
        - If a script imports other scripts (or service), it gets prioritized (TO DO when examples are available)
        - If several scripts are available, those at root level are prioritized (TO DO when examples are available)
    :param soft_invocation_info_list JSON list with the different ways to execute a program.
    """
    if len(soft_invocation_info_list) == 0:
        return soft_invocation_info_list
    # Calculate score for every entry in the list
    for entry in soft_invocation_info_list:
        score = 0
        if "library" in entry["type"] or "package" in entry["type"]:
            score += 100
        try:
            if entry["mentioned_in_readme"]:
                score += 10
        except:
            pass
        if "service" in entry["type"]:
            score += 5
        try:
            if "main" in entry["has_structure"]:
                score += 2
            if "body" in entry["has_structure"]:
                score += 1
        except:
            pass
        entry["ranking"] = score

    # Reorder vector and assign ranking
    soft_invocation_info_list.sort(key=lambda x: x["ranking"], reverse=True)

    # Replace score by number (but keep those with same score with the same ranking)
    position = 1
    previous_score = soft_invocation_info_list[0]["ranking"]
    for entry in soft_invocation_info_list:
        current_score = entry["ranking"]
        if previous_score > current_score:  # Ordered in descending order
            position += 1
            previous_score = current_score
        entry["ranking"] = position
    return soft_invocation_info_list
