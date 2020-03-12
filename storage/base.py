"""Provides unified shortcuts/interfaces for access folders and files.
"""
import os
import logging
from io import FileIO
from tempfile import NamedTemporaryFile
from urllib.parse import urlparse
from io import RawIOBase, UnsupportedOperation, SEEK_SET, DEFAULT_BUFFER_SIZE
logger = logging.getLogger(__name__)


class StorageObject:
    """Represents a storage object.
    This is the base class for storage folder and storage file.

    """

    def __init__(self, uri):
        """Initializes a storage object.

        Args:
            uri (str): Uniform Resource Identifier for the object.
            The uri should include a scheme, except local files.

        See https://en.wikipedia.org/wiki/Uniform_Resource_Identifier
        """
        self.uri = str(uri)
        parse_result = urlparse(self.uri)
        self.hostname = parse_result.hostname
        self.path = parse_result.path
        self.scheme = parse_result.scheme
        # Use file as scheme if one is not in the URI
        if not self.scheme:
            self.scheme = 'file'
            if not str(self.path).startswith("/"):
                self.path = os.path.abspath(self.path)
            self.uri = "file://" + self.uri

    def __str__(self):
        """Returns the URI
        """
        return self.uri

    def __repr__(self):
        return self.uri

    @property
    def basename(self):
        """The basename of the file/folder, without path or "/".

        Returns:
            str: The basename of the file/folder
        """
        return os.path.basename(self.path.strip("/"))

    @property
    def name(self):
        """The basename of the file/folder, without path or "/".
        Same as basename.

        Returns:
            str: The basename of the file/folder
        """
        return self.basename

    @staticmethod
    def get_attributes(storage_objects, attribute):
        """Gets the attributes of a list of storage objects.

        Args:
            storage_objects (list): A list of Storage Objects, from which the values of an attribute will be extracted.
            attribute (str): A attribute of the storage object.

        Returns (list): A list of attribute values.

        """
        if not storage_objects:
            return []
        elif not attribute:
            return [str(f) for f in storage_objects]
        else:
            return [getattr(f, attribute) for f in storage_objects]

    @staticmethod
    def copy_stream(from_file_obj, to_file_obj):
        """Copies data from one file object to another
        """
        chunk_size = DEFAULT_BUFFER_SIZE
        file_size = 0
        while True:
            b = from_file_obj.read(chunk_size)
            if not b:
                break
            file_size += to_file_obj.write(b)
        to_file_obj.flush()
        return file_size

    def create_temp_file(self, delete=False, **kwargs):
        """Creates a NamedTemporaryFile on local computer with the same file extension.
        Everything after the first dot is considered as extension
        """
        # Determine the file extension
        if "suffix" not in kwargs:
            arr = self.basename.split(".", 1)
            if len(arr) > 1:
                suffix = ".%s" % arr[1]
                kwargs["suffix"] = suffix

        temp_obj = NamedTemporaryFile('w+b', delete=delete, **kwargs)
        logger.debug("Created temp file: %s" % temp_obj.name)
        return temp_obj


class BucketStorageObject(StorageObject):
    """Represents a cloud storage object associated with a bucket.

    Attributes:
        prefix: The path on the bucket without the beginning "/"

    """
    def __init__(self, uri):
        StorageObject.__init__(self, uri)
        self._client = None
        self._bucket = None
        # The "prefix" for gcs does not include the beginning "/"
        if self.path.startswith("/"):
            self.prefix = self.path[1:]
        else:
            self.prefix = self.path
        self._blob = None

    @property
    def bucket_name(self):
        """The name of the Cloud Storage bucket as a string."""
        return self.hostname

    @property
    def client(self):
        if not self._client:
            self._client = self.init_client()
        return self._client

    @property
    def bucket(self):
        if not self._bucket:
            self.get_bucket()
        return self._bucket

    def is_file(self):
        if self.path.endswith("/"):
            return False
        if not self.exists():
            return False
        return True

    def init_client(self):
        raise NotImplementedError()

    def get_bucket(self):
        raise NotImplementedError()

    def exists(self):
        raise NotImplementedError()


class StorageFolderBase(StorageObject):
    def __init__(self, uri):
        # Make sure uri ends with "/" for folders
        if uri and uri[-1] != '/':
            uri += '/'
        StorageObject.__init__(self, uri)

    @property
    def file_paths(self):
        """

        Returns: A list of URIs, each points to a file in the folder.

        """
        raise NotImplementedError()

    @property
    def folder_paths(self):
        """

        Returns: A list of URIs, each points to a folder in the folder.

        """
        raise NotImplementedError()

    def exists(self):
        """Checks if the folder exists.
        """
        raise NotImplementedError()

    def create(self):
        raise NotImplementedError()

    def copy(self, to):
        raise NotImplementedError()

    def delete(self):
        raise NotImplementedError()


class StorageIOBase(StorageObject, RawIOBase):
    """Base class designed to provide:
        1. The underlying RawIO for a BufferedIO.
        2. High level operations like copy() and delete().

    StorageIOBase is an extension of the python RawIOBase
    See Also: https://docs.python.org/3/library/io.html#class-hierarchy

    The RawIO in StorageIOBase implementation is similar to the implementation of FileIO
    A sub-class of StorageIOBase can be used in place of FileIO
    Each sub-class should implement:
        read(), for reading bytes from the file.
        write(), for writing bytes into the file.
        close(), for closing the file.
        open(), should also be implemented if needed.

    In addition to interface provided by RawIOBase,
    StorageIOBase also defines some high level APIs.
    For high level operations, a sub-class should implement:
        size, the size of the file in bytes .
        exists(), determine if a file exists.
        delete(), to delete the file.
        load_from(), to load/create the file from a stream.

    Optionally, the following methods can be implemented
        to speed up the corresponding high-level operations.
        copy()
        local()
        upload()
        download()

    StorageIOBase and its sub-classes are intended to be the underlying raw IO of StorageFile.
    In general, they should not be used directly. The StorageFile class should be used instead.

    The file is NOT opened when initializing StorageIOBase with __init__().
    To open the file, call open() or use StorageIOBase.init().
    The close() method should be called after writing data into the file.
    Alternatively, the context manager can be used, e.g. "with StorageIOBase(uri) as f:"


    See Also:
        https://docs.python.org/3/library/io.html#io.FileIO
        https://docs.python.org/3/library/io.html#io.BufferedIOBase
        https://github.com/python/cpython/blob/1ed61617a4a6632905ad6a0b440cd2cafb8b6414/Lib/_pyio.py#L1461

    """
    def __init__(self, uri):
        StorageObject.__init__(self, uri)
        # Subclasses can use the following attributes
        self._closed = True
        # The following can be set by calling __set_mode(mode)
        # Raw IO always operates in binary mode
        self._mode = None
        self._created = False
        self._readable = False
        self._writable = False
        self._appending = False

    def __str__(self):
        """The URI of the file.
        """
        return self.uri

    def __call__(self, mode='rb'):
        self._set_mode(mode)
        return self

    @property
    def closed(self):
        return self._closed

    @property
    def mode(self):
        return self._mode

    def _set_mode(self, mode):
        """Sets attributes base on the mode.

        See Also: https://docs.python.org/3/library/functions.html#open

        """
        self._mode = mode
        # The following code is modified based on the __init__() of python FileIO class
        if not set(mode) <= set('xrwab+'):
            raise ValueError('Invalid mode: %s' % (mode,))
        if sum(c in 'rwax' for c in mode) != 1 or mode.count('+') > 1:
            raise ValueError('Must have exactly one of create/read/write/append '
                             'mode and at most one plus')

        if 'x' in mode:
            self._created = True
            self._writable = True
        elif 'r' in mode:
            self._readable = True
        elif 'w' in mode:
            self._writable = True
        elif 'a' in mode:
            self._writable = True
            self._appending = True
        if '+' in mode:
            self._readable = True
            self._writable = True

    def _is_same_mode(self, mode):
        if not self.mode:
            return False
        if mode:
            return sorted(self.mode) == sorted(mode)
        return True

    def open(self, mode='r', *args, **kwargs):
        if not self._is_same_mode(mode):
            self._set_mode(mode)
        self._closed = False
        return self

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
        return

    def _check_readable(self):
        """Checks if the file is readable, raise an UnsupportedOperation exception if not.
        """
        if not self.readable():
            raise UnsupportedOperation("File is not opened for read.")

    def _check_writable(self):
        """Checks if the file is writable, raise an UnsupportedOperation exception if not.
        """
        if not self.writable():
            raise UnsupportedOperation("File is not opened for write.")

    def writable(self):
        """Writable if file is writable and not closed.
        """
        return True if self._writable and not self._closed else False

    def readable(self):
        """Returns True if the file exists and readable, otherwise False.
        """
        if self._readable:
            return True
        return False

    def readall(self):
        """Reads all data from the file.

        Returns (bytes): All data in the file as bytes.

        """
        return self.read()

    def readinto(self, b):
        """Reads bytes into a pre-allocated bytes-like object b.

        Returns: An int representing the number of bytes read (0 for EOF), or
            None if the object is set not to block and has no data to read.

        This function is copied from FileIO.readinto()
        """
        # Copied from FileIO.readinto()
        m = memoryview(b).cast('B')
        data = self.read(len(m))
        n = len(data)
        m[:n] = data
        return n

    @property
    def size(self):
        return None

    @property
    def updated_time(self):
        """Last updated/modified time of the file as a datetime object.
        """
        raise NotImplementedError()

    def close(self):
        self._closed = True
        raise NotImplementedError("close() is not implemented for %s" % self.__class__.__name__)

    def read(self, size=None):
        """Reads at most "size" bytes.

        Args:
            size: The maximum number of bytes to be returned

        Returns (bytes): At most "size" bytes from the file.
            Returns empty bytes object at EOF.

        """
        self._check_readable()
        raise NotImplementedError()

    def write(self, b):
        """Writes bytes b to file.

        Returns: The number of bytes written into the file.
            None if the write would block.
        """
        self._check_writable()
        raise NotImplementedError()

    def exists(self):
        """Checks if the file exists.
        """
        raise NotImplementedError("exists() is not implemented for %s" % self.__class__.__name__)

    def delete(self):
        raise NotImplementedError()

    def load_from(self, stream):
        """Creates/Loads the file from a stream
        """
        if self.closed:
            with self.open("wb") as f:
                file_size = self.copy_stream(stream, f)
        else:
            file_size = self.copy_stream(stream, self)
        return file_size

    def download(self, to_file_obj):
        raise UnsupportedOperation()

    def upload(self, from_file_obj):
        raise UnsupportedOperation()


class StorageIOSeekable(StorageIOBase):
    """Base class for seekable Storage
    Seekable storage sub-class should implement:
        seek()
        tell()

    This class has an _offset attribute to help keeping track of the read/write position of the file.
    A sub-class may not use the _offset attribute if the underlying IO keeps track of the position.
    However, if the _offset is used, the read() and write() in the sub-class are responsible to update the _offset.
    Otherwise the _offset will always be 0.

    _seek() provides a simple implementation of seek().
    
    """
    def __init__(self, uri):
        StorageIOBase.__init__(self, uri)
        self._offset = 0

    def seekable(self):
        return True

    def _seek(self, pos, whence=SEEK_SET):
        """Move to new file position.
        Argument offset is a byte count.  Optional argument whence defaults to
        SEEK_SET or 0 (offset from start of file, offset should be >= 0); other values
        are SEEK_CUR or 1 (move relative to current position, positive or negative),
        and SEEK_END or 2 (move relative to end of file, usually negative, although
        many platforms allow seeking beyond the end of a file).
        Note that not all file objects are seekable.
        """
        if not isinstance(pos, int):
            raise TypeError('pos must be an integer.')
        if whence == 0:
            if pos < 0:
                raise ValueError("negative seek position %r" % (pos,))
            self._offset = pos
        elif whence == 1:
            self._offset = max(0, self._offset + pos)
        elif whence == 2:
            self._offset = max(0, self.size + pos)
        else:
            raise ValueError("whence must be 0, 1 or 2.")
        return self._offset

    @property
    def size(self):
        """Returns the size in bytes of the file as an integer.
        """
        raise NotImplementedError()

    def seek(self, pos, whence=SEEK_SET):
        raise NotImplementedError()

    def tell(self):
        raise NotImplementedError()


class CloudStorageIO(StorageIOSeekable):
    def __init__(self, uri):
        """
        """
        StorageIOSeekable.__init__(self, uri)

        # Path of the temp local file
        self.temp_path = None

        # Stores the temp local FileIO object
        self.__file_io = None

    @property
    def size(self):
        if self.__file_io:
            return os.fstat(self.__file_io.fileno).st_size
        return self.get_size()

    def seek(self, pos, whence=0):
        if self.__file_io:
            self._offset = self.__file_io.seek(pos, whence)
            return self._offset
        return self._seek(pos, whence)

    def tell(self):
        if self.__file_io:
            self._offset = self.__file_io.tell()
        return self._offset

    def local(self):
        """Creates a local copy of the file.
        """
        if not self.__file_io:
            file_obj = self.create_temp_file()
            # Download file if appending or updating
            if self.exists() and ('a' in self.mode or '+' in self.mode):
                self.download(file_obj)
            # Close the temp file and open it with FileIO
            file_obj.close()
            mode = "".join([c for c in self.mode if c in "rw+ax"])
            self.__file_io = FileIO(file_obj.name, mode)
            self.temp_path = file_obj.name
        return self

    # For reading
    def read(self, size=None):
        """Reads the file from the Google Cloud bucket to memory

        Returns: Bytes containing the contents of the file.
        """
        start = self.tell()
        if self.__file_io:
            self.__file_io.seek(start)
            b = self.__file_io.read(size)
        else:
            if not self.exists():
                raise FileNotFoundError("File %s does not exists." % self.uri)
            file_size = self.size
            if not file_size:
                return b""
            # download_as_string() will raise an error if start is greater than size.
            if start > file_size:
                return b""
            end = file_size - 1
            if size:
                end = start + size - 1
            logger.debug("Reading from %s to %s" % (start, end))
            b = self.read_bytes(start, end)
        self._offset += len(b)
        return b

    def write(self, b):
        """Writes data into the file.

        Args:
            b: Bytes data

        Returns: The number of bytes written into the file.

        """
        if self.closed:
            raise ValueError("write to closed file %s" % self.uri)
        # Create a temp local file
        self.local()
        # Write data from buffer to file
        self.__file_io.seek(self.tell())
        size = self.__file_io.write(b)
        self._offset += size
        return size

    def __rm_temp(self):
        if self.temp_path and os.path.exists(self.temp_path):
            os.unlink(self.temp_path)
        logger.debug("Deleted temp file %s of %s" % (self.temp_path, self.uri))
        self.temp_path = None
        return

    def open(self, mode='r', *args, **kwargs):
        """Opens the file for writing
        """
        if not self._closed:
            self.close()
        super().open(mode)
        self._closed = False
        # Reset offset position when open
        self.seek(0)
        if 'a' in self.mode:
            # Move to the end of the file if open in appending mode.
            self.seek(0, 2)
        elif 'w' in self.mode:
            # Create empty local file
            self.local()
        return self

    def close(self):
        """Flush and close the file.
        This method has no effect if the file is already closed.
        """

        if self._closed:
            return

        if self.__file_io:
            if not self.__file_io.closed:
                self.__file_io.close()
            self.__file_io = None

        if self.temp_path:
            logger.debug("Uploading file to %s" % self.uri)
            with open(self.temp_path, 'rb') as f:
                self.upload(f)
            # Remove __temp_file if it exists.
            self.__rm_temp()
            # Set _closed attribute
            self._closed = True

    @property
    def updated_time(self):
        raise NotImplementedError()

    def exists(self):
        raise NotImplementedError()

    def get_size(self):
        raise NotImplementedError()

    def delete(self):
        raise NotImplementedError()

    def upload(self, from_file_obj):
        raise NotImplementedError()

    def download(self, to_file_obj):
        """Downloads the data to a file object
        Caution: This method does not call flush()
        """
        raise NotImplementedError()

    def read_bytes(self, start, end):
        """Reads bytes from position start to position end, inclusive
        """
        raise NotImplementedError()



