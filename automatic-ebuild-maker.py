#!/usr/bin/env python3

from datetime import date
from glob import glob
from json import load
from optparse import OptionParser
from os import mkdir, path
from re import sub
from signal import signal, SIGINT
from sys import stdout
from wget import download

import tarfile
import unix_ar

CACHE_DIR = '/tmp/automatic-ebuild-maker-cache/'


class Deb:
    """Class representing .deb file"""
    url = ''
    cache_dir = ''
    location = ''
    filename = ''
    architecture = ''

    ARCHIVES = ['control.tar.gz', 'data.tar.xz']

    def __init__(self, url, cache_directory=CACHE_DIR, arch=''):
        if url:
            self.url = url
            self.cache_dir = cache_directory
            self.filename = url.split('/')[-1]
            self.dirname = self.filename.split('/')[-1].replace('.', '-')
            self.extract_location = self.cache_dir + self.dirname
        self.architecture = arch

    def is_downloaded(self):
        if not self.filename:
            return False
        return path.isfile(self.cache_dir + self.filename)

    def download(self):
        if self.filename:
            print_bold(f'\nDownloading target file to {self.cache_dir + self.filename}\n')
            print(f'{self.url}\n')
            self.location = download(self.url, self.cache_dir + self.filename)
            print('\n')

    def is_extracted(self):
        return path.isdir(self.cache_dir + self.dirname)

    def extract(self):
        if self.is_downloaded():
            print_bold(f'\nFile {self.filename} already downloaded in cache.')
            self.location = self.cache_dir + self.filename
            print(f'{self.location}\n')
        else:
            self.download()

        ar_file = unix_ar.open(self.location)

        for archive in self.ARCHIVES:
            print(f'Extracting {archive}', end=' ')
            stdout.flush()
            folder = archive.split(".")[0]
            if path.isdir(f'{self.extract_location}/{folder}'):
                print('[already extracted]')
            else:
                state = ''
                for info in ar_file.infolist():
                    if info.name.decode('utf-8') in [f'{archive}', f'{archive}/']:
                        tarball = ar_file.open(info.name.decode('utf-8'))
                        tar_file = tarfile.open(fileobj=tarball)
                        tar_file.extractall(f'{self.extract_location}/{folder}')
                        print('[done]')
                        state = 'ok'
                        break

                if not state:
                    print_warning('[failed]')
                    quit()

    def get_control_data(self):
        if self.is_extracted():
            print_bold(f'\nFile {self.filename} already extracted in cache.')
            print(f'{self.extract_location}\n')
        else:
            self.extract()

        data = {}
        with open(self.extract_location + '/control/control') as control_file:
            line = control_file.readline()
            while line:
                key, value = line.split(': ', 1)
                if key == 'Description':
                    long_description = ''.join(control_file.readlines()).replace('  ', '').replace('\n', '')
                    if long_description:
                        data['Long description'] = long_description

                    inline_description = value.replace('\n', '')
                    if inline_description:
                        data[key] = inline_description
                    else:
                        data[key] = long_description

                else:
                    data[key] = value.replace('\n', '')

                line = control_file.readline()

        dependencies = []
        if 'Depends' in data:
            dependencies += data['Depends'].split(', ')
        if 'Recommends' in data:
            dependencies += data['Recommends'].split(', ')
            data.pop('Recommends')
        if 'Suggests' in data:
            dependencies += data['Suggests'].split(', ')
            data.pop('Suggests')
        data['Depends'] = dependencies

        if 'Architecture' in data:
            self.architecture = data['Architecture']

        return data


class Ebuild:
    """Class representing .ebuild file"""
    package = ''
    version = ''

    eapi = 7
    inherit = []
    description = ''
    long_description = ''
    homepage = ''
    src_uri = {}
    license = ''
    slot = 0
    restrict = ['bindist', 'mirror']
    use_flags = []
    tmp_use_flags = []
    deb_dependencies = []
    dependencies = []
    use_dependencies = {}

    postinst = []
    postrm = []

    root = ''
    native_bin = ''

    unnecessary_files = {}
    desktop_files = []
    doc_directory = ''
    archives_in_doc_directory = []
    potencial_run_files = []

    deb_files = []
    deb_data = []

    def __init__(self, *_, deb_files: [Deb] = None):

        if deb_files:
            # Making ebuild from .deb

            self.deb_files = deb_files
            deb_file = deb_files[0]
            data = deb_file.get_control_data()
            self.deb_data = data
            self.inherit.append('unpacker')

            if 'Package' in data:
                self.package = data['Package']
            else:
                self.package = 'unknown'
                warnings.append(f'Package name not found. Using "{self.version}" instead.')

            if 'Version' in data:
                self.version = data['Version'].split('-')[0]
            else:
                self.version = '1.0.0'
                warnings.append(f'Package version not found. Using "{self.version}" instead.')

            if 'Homepage' in data:
                self.homepage = data['Homepage']
            else:
                warnings.append('Package homepage is missing.')

            if 'License' in data:
                self.license = data['License'].replace('v', '-')
            else:
                warnings.append('Package license is missing.')

            if 'Description' in data:
                self.description = data['Description']
            else:
                warnings.append('Package description is missing.')

            if 'Long description' in data:
                self.long_description = data['Long description']
            else:
                warnings.append('Package long description is missing.')

            self.root = deb_file.extract_location + '/data/'

            if options.system_ffmpeg:
                self.tmp_use_flags.append('system-ffmpeg')

            if options.system_mesa:
                self.tmp_use_flags.append('system-mesa')

            self.parse_dependencies_from_deb()
            self.update_unnecessary_files()
            self.update_desktop_files()
            self.update_doc_directory()
            self.update_archives_in_directory(self.doc_directory)
            self.update_potencial_run_files()
            # self.update_use_dependencies()

    def name(self):
        return f'{self.package.replace(".", "-")}-{self.version}.ebuild'

    def add_deb_file(self, deb_file):
        if deb_file not in self.deb_files:
            self.deb_files.append(deb_file)

    def add_use_flag(self, use):
        if use not in self.use_flags:
            self.use_flags.append(use)
            self.use_flags.sort()

    def get_architectures(self):
        return list(self.get_src_uris().keys())

    def get_src_uris(self):
        uris = {}

        if self.deb_files:
            for deb in self.deb_files:
                arch = deb.architecture
                if arch:
                    uris[arch] = deb.url
        return uris

    def parse_dependencies_from_deb(self):
        deb_dependencies = self.deb_data['Depends']
        dependencies = []

        def cut_version(depencency):
            return sub(r' \(.*\)', '', depencency)

        for dep in deb_dependencies:
            if '|' in dep:
                multi_dep = dep.split(' | ')
                for i in range(len(multi_dep)):
                    multi_dep[i] = cut_version(multi_dep[i])
                dependencies.append(multi_dep)
                continue
            dependencies.append(cut_version(dep))
        self.deb_dependencies = dependencies

    def convert_dependencies(self, dependencies):

        def convert_dependency(d):
            if d in database['dependencies']:
                return database['dependencies'][d], False
            if d in database['dependencies-optional']:
                dep_use = database['dependencies-optional'][d]
                return database['use-dependencies'][dep_use], dep_use
            return False, False

        result = []
        for dep in dependencies:
            if isinstance(dep, list):
                converted = self.convert_dependencies(dep)
                if len(converted) > 1:
                    result.append(converted)
                else:
                    result += converted
            else:
                converted = convert_dependency(dep)
                if converted[0]:
                    if converted not in result:
                        result.append(converted)
                else:
                    warnings.append(f'Gentoo alternative dependency for \"{dep}\" not found in database.json.')
        return result

    def build_dependencies_string_2(self):
        dependencies = self.convert_dependencies(self.deb_dependencies)

        normal_dependencies = []
        multi_dependencies = []
        use_dependencies = {}

        for dep in dependencies:
            if isinstance(dep, list):
                dep.sort()
                multi_dependencies.append(dep)
            else:
                if dep[1]:
                    use_dependencies[dep[1]] = dep[0]
                    self.add_use_flag(dep[1])
                else:
                    normal_dependencies.append(dep[0])

        for use in self.tmp_use_flags:
            if use in database['use-dependencies']:
                use_dependencies[use] = database['use-dependencies'][use]

        normal_dependencies.sort()
        multi_dependencies.sort()

        string = ''
        c = 0
        for dep in normal_dependencies:
            string += ("" if c == 0 else "\n\t") + f'{dep}'
            c += 1

        keys = list(use_dependencies.keys())
        keys.sort()

        for use in keys:
            string += ("" if c == 0 else "\n\t") + f'{use}? ( {use_dependencies[use]} )'
            c += 1

        for group in multi_dependencies:
            string += ("" if c == 0 else "\n\t") + '|| ('
            for dep in group:
                if dep[1]:
                    string += f'\n\t\t{dep[1]}? ( {dep[0]} )'
                else:
                    string += f'\n\t\t{dep[0]}'
            string += f'\n\t)'
            c += 1

        return string

    # def update_dependencies_from_deb(self):
    #     deb_dependencies = self.deb_data['Depends']
    #     for dep in deb_dependencies:
    #         if '|' in dep:
    #             state = ''
    #             for sp_dep in dep.split(' | '):
    #                 if sp_dep in database['dependencies-optional']:
    #                     self.add_use_flag(database['dependencies-optional'][sp_dep])
    #                     state = 'ok'
    #                 elif sp_dep in database['dependencies']:
    #                     if database['dependencies'][sp_dep] not in self.dependencies:
    #                         self.dependencies.append(database['dependencies'][sp_dep])
    #                         state = 'ok'
    #             if not state:
    #                 warnings.append(f'Gentoo alternative dependency for \"{dep}\" not found in database.json.')
    #
    #         elif dep in database['dependencies-optional']:
    #             self.add_use_flag(database['dependencies-optional'][dep])
    #
    #         elif dep in database['dependencies']:
    #             if database['dependencies'][dep] not in self.dependencies:
    #                 self.dependencies.append(database['dependencies'][dep])
    #         else:
    #             warnings.append(f'Gentoo alternative dependency for \"{dep}\" not found in database.json.')
    #
    #     self.dependencies.sort()

    def update_unnecessary_files(self):
        for use in self.tmp_use_flags:
            if use in database['unnecessary-files']:
                files = database['unnecessary-files'][use]
                found = []
                for unnecessary_file in files:
                    found += find_files(self.root, f'**/{unnecessary_file}')
                tmp = []
                for f1 in found:
                    state = True
                    for f2 in found:
                        if f2 in f1 and f1 != f2:
                            state = False
                    if state:
                        tmp.append(f1)
                if tmp:
                    # tmp.sort()
                    self.unnecessary_files[use] = tmp
                    self.add_use_flag(use)

    def update_desktop_files(self):
        self.desktop_files = find_files(self.root, '**/*.desktop')
        if self.desktop_files:
            self.inherit.append('xdg')
        else:
            warnings.append('No desktop files found.')

    def update_doc_directory(self):
        found = find_files(self.root, 'usr/share/doc/*')
        if found:
            self.doc_directory = found[0]
            if self.doc_directory:
                self.add_use_flag('doc')

    def update_archives_in_directory(self, directory):
        found = find_files(self.root + directory + '/', '**/*.gz')
        for item in found:
            self.archives_in_doc_directory.append(directory + '/' + item)

    def update_potencial_run_files(self):
        if self.desktop_files:
            for desktop_file in self.desktop_files:
                with open(self.root + desktop_file) as desktop:
                    lines = desktop.readlines()
                for line in lines:
                    if 'Exec=' in line:
                        command = line.replace('Exec=', '').replace('\n', '').split(' ')[0]
                        if len(command.split('/')) > 1:
                            if command[0] == '/':
                                command = command[1:]
                            self.potencial_run_files.append(command)
                            if 'usr/bin' in command:
                                self.native_bin = command
            if self.potencial_run_files:
                return

        patterns = [self.package,
                    self.package.capitalize(),
                    self.package.replace('-desktop', ''),
                    self.package.replace('-desktop', '').capitalize()]

        for pattern in patterns:
            tmp = find_files(self.root, f'**/{pattern}')
            for item in tmp:
                if item not in self.potencial_run_files and path.isfile(self.root + item):
                    self.potencial_run_files.append(item)
                    if 'usr/bin' in item:
                        self.native_bin = item

        if not self.native_bin and not self.potencial_run_files:
            warnings.append('No executable files found.')

    # def update_use_dependencies(self):
    #     for use in self.use_flags:
    #         if use in database['use-dependencies']:
    #             self.use_dependencies[use] = database['use-dependencies'][use]

    def build_src_uri_string(self):
        pv = '${PV}'

        src_uri_string = ''

        counter = 0
        src_uris = self.get_src_uris()
        for arch in src_uris:
            suffix = src_uris[arch].split('.')[-1]
            url = src_uris[arch].replace(self.version, pv)
            keyword = arch
            if keyword == 'i386' or keyword == 'i686':
                keyword = 'x86'
            if counter == 0:
                if len(src_uris) == 1:
                    src_uri_string = f'{url} -> {self.package}-{pv}.{suffix}'
                else:
                    src_uri_string += f'{keyword}? ( {url} -> {self.package}-{pv}-{arch}.{suffix} )'
            else:
                src_uri_string += f'\n\t{keyword}? ( {url} -> {self.package}-{pv}-{arch}.{suffix} )'
            counter += 1
        return src_uri_string

    def build_keywords_string(self):
        string = '-* ~' + ' ~'.join(self.get_architectures())
        string = string.replace('i386', 'x86')
        return string.replace('i686', 'x86')

    # def build_dependencies_string(self):
    #     string = ''
    #     counter = 0
    #     for dep in self.dependencies:
    #         if counter == 0:
    #             string += f'{dep}'
    #         else:
    #             string += f'\n\t{dep}'
    #         counter += 1
    #
    #     for use in self.use_dependencies:
    #         string += f'\n\t{use}? ( {self.use_dependencies[use]} )'
    #     return string

    def build_src_prepare_string(self):
        result = ''

        if self.archives_in_doc_directory and 'doc' in self.use_flags:
            result += f'\n\tif use doc ; then\n'
            for archive in self.archives_in_doc_directory:
                result += f'\t\tunpack "{archive}" || die "unpack failed"\n'
                result += f'\t\trm -f "{archive}" || die "rm failed"\n'
                extracted_location = ".".join(archive.split("/")[-1].split(".")[:-1])
                target_location = '/'.join(archive.split('/')[:-1])
                result += f'\t\tmv "{extracted_location}" "{target_location}" || die "mv failed"\n'
            result += '\tfi\n'

        if self.unnecessary_files:
            for use in self.unnecessary_files:
                result += f'\n\tif use {use} ; then\n'
                for f in self.unnecessary_files[use]:
                    result += f'\t\trm -f{"r" if path.isdir(self.root + f) else " "} "{f}" || die "rm failed"\n'
                result += '\tfi\n'

        return result

    def build_src_install_string(self):
        result = ''

        result += '\tcp -a . "${ED}" || die "cp failed"'

        if self.doc_directory:
            ed = "${ED}"
            result += f'\n\n\trm -r "{ed}/{self.doc_directory}" || die "rm failed"'

        if self.doc_directory:
            result += '\n\n\tif use doc ; then\n'
            result += f'\t\tdodoc -r "{self.doc_directory}/"* || die "dodoc failed"\n'
            result += '\tfi'

        if self.unnecessary_files:
            for use in self.unnecessary_files:
                if use in database["use-symlinks"]:
                    result += f'\n\n\tif use {use} ; then\n'
                    for f in self.unnecessary_files[use]:
                        result += f'\t\tdosym \"{database["use-symlinks"][use]}\" \"/{f}\" || die "dosym failed"\n'
                    result += '\tfi'

        if not self.native_bin and self.potencial_run_files:
            result += '\n\n'
            exe = self.potencial_run_files[0]
            result += f'\tdosym "/{exe}" "/usr/bin/{ebuild.package}" || die "dosym failed"'

        return result

    # def build_pkg_postinst_string(self):
    #     result = ''
    #
    #     if self.root and self.desktop_files:
    #         result += '\txdg_icon_cache_update\n'
    #         result += '\txdg_desktop_database_update'
    #
    #         for desktop in self.desktop_files:
    #             with open(self.root + desktop) as file:
    #                 content = file.read()
    #                 if 'MimeType' in content:
    #                     result += '\n\txdg_mimeinfo_database_update'
    #
    #     return result
    #
    # def build_pkg_postrm_string(self):
    #     result = ''
    #
    #     if self.root and self.desktop_files:
    #         result += '\txdg_desktop_database_update'
    #
    #         for desktop in self.desktop_files:
    #             with open(self.root + desktop) as file:
    #                 content = file.read()
    #                 if 'MimeType' in content:
    #                     result += '\n\txdg_mimeinfo_database_update'
    #
    #     return result


class Colors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'


def verbose_print(string):
    """Print function that prints only if --verbose flag is present."""
    if options.verbose:
        print(string)


def print_warning(string):
    """Print function that prints in Colors.WARNING colors."""
    print(Colors.WARNING + string + Colors.ENDC)


def print_bold(string):
    """Print function that prints bold text."""
    print(Colors.BOLD + string + Colors.ENDC)


def print_ok(string):
    """Print function that prints green text."""
    print(Colors.OKGREEN + string + Colors.ENDC)


def quit_handler(_, __):
    """Handler for exit signal."""
    print('\nSIGINT or CTRL-C detected. Exiting')
    quit()


def find_files(root, pattern, cut_root=True):
    result = []
    found = glob(root + pattern, recursive=True)
    for item in found:
        if cut_root:
            result.append(item.replace(root, ''))
        else:
            result.append(item)
    return result


if __name__ == '__main__':

    signal(SIGINT, quit_handler)

    parser = OptionParser()

    parser.add_option('', '--system-ffmpeg',
                      action='store_true', dest='system_ffmpeg', default=False,
                      help='Try to include system-ffmpeg USE flag to the ebuild')
    parser.add_option('', '--system-mesa',
                      action='store_true', dest='system_mesa', default=False,
                      help='Try to include system-mesa USE flag to the ebuild')
    parser.add_option('-v', '--verbose',
                      action='store_true', dest='verbose', default=False,
                      help='run script in verbose mode')
    parser.add_option('-u', '--url', dest='url',
                      help='specify input package file url',
                      metavar='<package_url>')

    parser.add_option('', '--amd64', action='store_true', dest='amd64',
                      default=False, help='package is available for amd64 <arch>')
    parser.add_option('', '--i386', action='store_true', dest='i386',
                      default=False, help='package is available for i386 <arch>')
    parser.add_option('', '--i686', action='store_true', dest='i686',
                      default=False, help='package is available for i686 <arch>')

    (options, args) = parser.parse_args()

    # Set constant variables

    REAL_PATH = path.dirname(path.realpath(__file__))
    DATABASE_FILE = REAL_PATH + '/database.json'
    TEMPLATES_DIR = REAL_PATH + '/templates/'

    if not options.url:
        print_warning('Input file not specifed. Please, use --input flag.')
        quit()

    if 'http://' not in options.url and 'https://' not in options.url:
        print('Wrong input %s' % options.url)
        print_warning('Input file has to be specifed by URL adress.')
        quit()

    architectures = []
    if options.amd64:
        architectures.append('amd64')
    if options.i386:
        architectures.append('i386')
    if options.i686:
        architectures.append('i686')

    if not path.isdir(CACHE_DIR):
        try:
            mkdir(CACHE_DIR)
        except OSError:
            print_warning(f'[error] Creation of the directory failed!')
            print('   -', CACHE_DIR)
            quit()

    file_suffix = options.url.split('.')[-1]
    if file_suffix == 'deb':

        src_uri = {}

        if '@ARCH@' in options.url:
            if architectures:
                for architecture in architectures:
                    src_uri[architecture] = options.url.replace('@ARCH@', architecture)
                options.url = src_uri[architectures[0]]
            else:
                print_warning('[error] You have to provide at least one architecture when using @ARCH@ in url')
                quit()

        warnings = []

        if path.isfile(DATABASE_FILE):
            verbose_print('\n[ok] Found database file:')
            verbose_print('   - %s' % DATABASE_FILE)
            with open(DATABASE_FILE) as json_file:
                database = load(json_file)
        else:
            print_warning('[warning] Database file not found.')
            database = {}

        input_files = []
        if src_uri:
            for architecture in src_uri:
                input_files.append(Deb(src_uri[architecture], arch=architecture))
        else:
            input_files.append(Deb(options.url))

        ebuild = Ebuild(deb_files=input_files)
        ebuild.add_deb_file(Deb(options.url))

        ebuild_data = {
            '@YEAR@': date.today().year,
            '@EAPI@': ebuild.eapi,
            '@INHERIT@': ' '.join(ebuild.inherit),
            '@DESCRIPTION@': ebuild.description,
            '@HOMEPAGE@': ebuild.homepage,
            '@SRC_URI@': ebuild.build_src_uri_string(),
            '@LICENSE@': ebuild.license,
            '@SLOT@': ebuild.slot,
            '@KEYWORDS@': ebuild.build_keywords_string(),
            '@RESTRICT@': ' '.join(ebuild.restrict),
            '@RDEPEND@': ebuild.build_dependencies_string_2(),
            '@IUSE@': ' '.join(ebuild.use_flags),
            '@QA_PREBUILT@': '*'
        }

        with open(TEMPLATES_DIR + 'template.ebuild') as template:
            template_content = template.read()

        for string_pattern in ebuild_data:
            template_content = template_content.replace(string_pattern, str(ebuild_data[string_pattern]))

        template_content += '\nS=${WORKDIR}\n'

        src_prepare_string = ebuild.build_src_prepare_string()

        if src_prepare_string:
            template_content += '\nsrc_prepare() {\n\tdefault\n'
            template_content += src_prepare_string
            template_content += '}\n'

        src_install_string = ebuild.build_src_install_string()

        if src_install_string:
            template_content += '\nsrc_install() {\n'
            template_content += src_install_string
            template_content += '\n}\n'

        ebuild_file = open(ebuild.name(), 'w')
        ebuild_file.write(template_content)

        if warnings:
            print_warning('Things that may require your attention:\n')
            for warning in warnings:
                print_bold(warning)
            print()

        print_ok(f'File {ebuild.name()} created.')

        metdata_file = open(f'{ebuild.package.replace(".", "-")}-metadata.xml', 'w')
        metdata_file.writelines([
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<!DOCTYPE pkgmetadata SYSTEM "http://www.gentoo.org/dtd/metadata.dtd">\n'
            '<pkgmetadata>\n'
        ])

        if ebuild.description:
            metdata_file.write(f'\t<longdescription>\n\t\t{ebuild.long_description or ebuild.description}\n\t'
                               f'</longdescription>\n')

        if ebuild.use_flags:
            metdata_file.write('\t<use>\n')
            for use_flag in ebuild.use_flags:
                if use_flag in database['use-descriptions']:
                    metdata_file.write(f'\t\t<flag name="{use_flag}">{database["use-descriptions"][use_flag]}</flag>\n')
            metdata_file.write('\t</use>\n')

        metdata_file.write('</pkgmetadata>\n')
        metdata_file.close()

        print_ok(f'File {ebuild.package.replace(".", "-")}-metadata.xml created.')
